"""Assemble deliverables into research/hype_all_in_one/results/ (incremental, idempotent)."""
import json,pickle,csv,shutil,hashlib,os,gzip,collections
from pathlib import Path
import numpy as np,torch
import __main__,train_walkforward as W
__main__.Norm=W.Norm;__main__.CortexEarly=W.CortexEarly
from core import DATA,T0,day_list
R=Path("/workspace/pandora-testnet/research/hype_all_in_one/results");R.mkdir(parents=True,exist_ok=True)
M=json.load(open(DATA/"metrics_raw.json"));MF=json.load(open(DATA/"mfe_raw.json"))
TR=json.load(open(DATA/"teacher_repro.json"));SL=json.load(open(DATA/"survival_ladder.json"))
PRE=json.load(open("/workspace/hype_early/PREREGISTRATION.json"))
table=pickle.load(open(DATA/"per_local_table.pkl","rb"));sig=pickle.load(open(DATA/"signals.pkl","rb"))
ds=pickle.load(open(DATA/"dataset.pkl","rb"));rows=ds["rows"]
def sha(p):
    h=hashlib.sha256();f=open(p,"rb")
    for b in iter(lambda:f.read(1<<20),b""):h.update(b)
    return h.hexdigest()
# ---- feature availability / missingness by month & family
from atlas import fam,MONTHS,S
names=sorted({k for r in rows for k in r["features"]})
avail={}
for mn,a,b in MONTHS+[("Nov4-11 forward","2026-11-04","2026-11-12")]:
    rr=[r for r in rows if S(a)<=r["t"]<S(b)]
    if not rr:continue
    fam_av=collections.defaultdict(list)
    for k in names:fam_av[fam(k)].append(float(np.mean([k in r["features"] and np.isfinite(r["features"][k]) for r in rr[::5]])))
    avail[mn]={"rows":len(rr),"family_mean_availability":{f:round(float(np.mean(v)),4) for f,v in fam_av.items()}}
glob={k:round(float(np.mean([k in r["features"] and np.isfinite(r["features"][k]) for r in rows[::7]])),4) for k in names}
FEATURE_AVAIL={"by_month_family":avail,"per_feature_overall":glob,
    "unavailable_families":{"liquidations (contract ids 65-76)":"v2: AVAILABLE from public CryptoHFTData Bybit WS archive (received_time ns); hours without a file are MISSING (NaN+mask), never zero",
        "raw receive timestamps (77,78)":"v2: audited on project live WS capture (7.5h) and CryptoHFTData 48h raw; p99 latency 0.10-0.14 s trades/book, liquidations batched <=0.61 s; not a per-row model input historically",
        "runner clock offset (111)":"not reconstructable",
        "instrument metadata (112)":"constant metadata, not fitted"},
    "missing_policy":"NaN kept as missing; LightGBM native missing handling; MLP/JEPA get value+availability-mask pairs (repo vectorize convention); River/Cortex skip absent keys. Never zero-imputed as market evidence."}
# ---- v2 extras
J=lambda n:json.load(open(DATA/n)) if (DATA/n).exists() else None
TP_=J("teacher_project_repro.json")
V2X={"artifact_inventory":J("ARTIFACT_INVENTORY.json"),
 "teacher_on_project_compact_M1":{k:v for k,v in TP_["summary"].items()} if TP_ else None,
 "minute_alignment_project_vs_rebuilt_after_fix":J("align_project_vs_bybit.json"),
 "local116_snapshot_rebuild_alignment":J("p116_alignment.json"),
 "receive_time_latency_audit":J("latency_audit.json"),
 "liquidation_alignment":J("liq_alignment.json"),
 "project_checkpoints_forward_Nov4_11":J("project_ckpt_forward.json"),
 "version_comparison_v1_v2a_v2":J("version_comparison.json")}
# ---- success criteria (computed, not asserted)
ta=M["transfer_aggregate"]
P="B0.4_SAFE_MAX_OOF_CAL"
def fold_fp(cfg):return {fn:{s:M["folds"][fn][cfg][s]["false_first"] for s in ("LOW","HIGH")} for fn in ("WF_Jul","WF_Aug","WF_Sep","WF_Oct")}
def ff_total(cfg):return sum(v for f in fold_fp(cfg).values() for v in f.values())
C1=any(ff_total(c)==0 and ta[c]["COMBINED"]["tp"]>0 for c in (P,"B0.7_SAFE_MAX_OOF_CAL","B1.0_SAFE_MAX_OOF_CAL"))
crit={
 "C1_false_first_zero_all_transfer_folds":{"primary":fold_fp(P),"B0.7":fold_fp("B0.7_SAFE_MAX_OOF_CAL"),"B1.0":fold_fp("B1.0_SAFE_MAX_OOF_CAL"),"pass":bool(C1)},
 "C2_materially_earlier_than_teacher":{"primary_median_dist_pct":ta[P]["COMBINED"]["median_dist_pct"],"primary_coverage":ta[P]["COMBINED"]["coverage"],
     "teacher_median_dist_pct":ta["TEACHER_V1_same_episodes"]["COMBINED"]["median_dist_pct"],"teacher_coverage":ta["TEACHER_V1_same_episodes"]["COMBINED"]["coverage"],
     "pass":False,"why":"earlier entries exist only for ~1-3% of true Locals and come with more false-first than true-first"},
 "C3_captured_MFE_materially_higher":{"per_signal_median_captured_primary":ta[P]["COMBINED"]["median_captured_mfe_ratio"],"teacher":ta["TEACHER_V1_same_episodes"]["COMBINED"]["median_captured_mfe_ratio"],
     "system_level_net_capture":{k:v["net_local_to_local_capture_ratio"] for k,v in MF["transfer_aggregate"].items()},
     "pass":False,"why":"per-signal capture is higher when right, but system-level Local-to-Local capture is LOWER than teacher-only because of false-first and false protects"},
 "C4_transfers_across_regimes":{"pass":False,"why":"no candidate passed C1; regime table in metrics"},
 "C5_fresh_forward_confirms":{"forward_period":"2026-11-04..2026-11-11 (7 LOW + 7 HIGH matured terminal Locals)","primary_forward":M["forward"][P]["COMBINED"],
     "teacher_forward":M["forward"]["TEACHER_V1_same_episodes"]["COMBINED"],"pass":False,"why":"primary produced 0 signals on forward; sample is too small to confirm anything"},
 "VERDICT":("NOT_PASSED" if not C1 else "CHECK_MANUALLY")+" - no early (<=0.40/0.70/1.00%) causal detector with zero false-first exists in this data under frozen walk-forward. Best stable result remains the late V1 teacher. Pareto frontier delivered instead."}
# ---- metrics json
metrics={"version":"HYPE-EARLY-REAL-H1-LOCAL-v2","v2_extras":V2X,"research_only":True,"real_orders":False,
 "generated_local":os.popen("date '+%Y-%m-%d %H:%M %Z'").read().strip(),
 "preregistration":PRE,
 "teacher_alignment_reproduction":{"note":"V1 teacher (285m/130bps/0.80|0.75) replayed on tape rebuilt from Bybit public archives over the SAME plateau periods",
     "reported_in_repo":{"episodes":312,"accepted":101,"true_first":101,"false_first":0,"coverage":0.3237,"median_entry_distance_pct":2.47,"p90":4.18},
     "reproduced":TR["summary"]["ALL"],"per_period":{k:v for k,v in TR["summary"].items() if k!="ALL"},
     "differences":"v2: on the PROJECT's own compact M1 the teacher reproduces 312/101/101/0/32.37%/2.466% EXACTLY. On the rebuilt tape (after the v2 M1 open-second fix) May/Aug/Sep identical; Jul +2 episodes (+1 TP) from one trade at 2026-07-28 22:25 UTC present in Bybit archive but absent from the project's CryptoHFTData Jul tape, plus Jul period bounds (project tape 07-12 17:00..08-07 00:00); Oct +1 HIGH label at the period start (2026-10-04 10:21 UTC). v1 had an additional 1-tick M1 high/low artifact (forward-filled previous close entered minute high/low) - fixed in v2."},
 "teacher_on_continuous_history_2026-05-01..2026-11-11":{"source":"/workspace/data/teacher_continuous.json (v2 tape)","episodes":461,"accepted":152,"true_first":150,"false_first":2,
     "false_first_cases":["HIGH target 2026-05-02 09:10 UTC (signal 2026-05-01 08:07 UTC, lineage from Apr 30 - absent from repo May tape)","LOW target 2026-06-10 00:41 UTC (June - never part of the repo plateau set)"]},
 "dataset":{"unit":"lineage member (every new 6h-trailing extreme print at 1s resolution; more-extreme print supersedes)","rows":len(rows),
     "members":{"LOW":14240,"HIGH":19006},"episodes_2026-05-01..2026-11-11":461,
     "decision_points":["T0","T10","T30","T60","T180","T300","T600","T900","T1800","T3600","T7200","T10800","A15","A20","A25","A30","A35","A40","A50","A70","A100"],
     "label":"TRUE iff member == strict H1 L6/K2 terminal pivot of its episode (offline only)"},
 "walk_forward":{"folds":W.FOLDS,"purge":"train labels finalized and scoring deadline passed before calibration start; calibration labels finalized before test start",
     "threshold_policies":W.POLICIES,"budgets_pct":W.BUDGETS},
 "per_fold":M["folds"],"transfer_aggregate_Jul_Oct":ta,"forward_Nov4_Nov11":M["forward"],
 "pareto_points_transfer":M["pareto_transfer_all_points"],
 "oracle_frontier_DIAGNOSTIC_NOT_A_DETECTOR":M["oracle_frontier_diagnostic"],
 "survival_ladder_earlier_checkpoints_v1_not_rerun":{fn:{s:{k:v for k,v in x.items() if k!="test_records"} for s,x in f.items()} for fn,f in SL["folds"].items()},
 "regime_breakdown":M["regime_breakdown"],"feature_availability":FEATURE_AVAIL,"success_criteria":crit}
json.dump(metrics,open(R/"EARLY_REAL_H1_LOCAL_METRICS.json","w"),indent=1,default=float,ensure_ascii=False)
# atlas
A=json.load(open(DATA/"atlas.json"))
json.dump(A,open(R/"TRUE_FALSE_RELATIONSHIP_ATLAS.json","w"),indent=1,default=float,ensure_ascii=False)
# MFE
mfe={k:v for k,v in MF.items() if k!="transfer_aggregate"}
for fn in mfe:mfe[fn]={k:v for k,v in mfe[fn].items()}
json.dump({"definitions":{"REVERSE":"open full-size position in the Local direction (B1.0_SAFE_MAX_OOF_CAL early signal OR frozen V1 teacher)",
    "PROTECT":"exit an open position when the OPPOSITE side detector fires at B0.7_CAL_Q995","FALSE_RESET":"exit when the entry Local's extreme is broken (lineage invalidation)",
    "ideal":"sum of |swing| between consecutive strict H1 Locals in the period (perfect Local->Local)","fee":"0.055% per side taker (0.11% round trip) in net column",
    "captured_mfe_ratio(per signal)":"(next opposite Local - entry)/(next opposite Local - true Local)"},
    "transfer_aggregate_Jul_Oct":MF["transfer_aggregate"],"per_period":mfe,
    "per_signal_capture":{"primary":ta[P],"B1.0":ta["B1.0_SAFE_MAX_OOF_CAL"],"teacher":ta["TEACHER_V1_same_episodes"]}},
    open(R/"MFE_CAPTURE_REPORT.json","w"),indent=1,default=float,ensure_ascii=False)
# signals CSV
with open(R/"EARLY_LOCAL_REPLAY_SIGNALS.csv","w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=list(sig[0].keys()));w.writeheader();w.writerows(sig)
with open(R/"PER_LOCAL_ENTRY_DISTANCE.csv","w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=list(table[0].keys()));w.writeheader();w.writerows(table)
# model bundle: frozen FINAL model (+ fold models' thresholds), teacher rules
fb=torch.load(DATA/"bundle_FINAL_FORWARD.pt",weights_only=False)
from research.hype_terminal_local_strategy.h1_real_local_detector_v1 import RULES
bundle={"version":"HYPE-EARLY-LOCAL-BUNDLE-v2","research_only":True,"real_orders":False,"status":"REJECTED_FOR_PROMOTION (criteria not met) - research artifact only",
  "frozen_final_model":{s:{"feature_names":v["names"],"experts":v["experts"],"meta":v["meta"],"thresholds":v["thresholds"]} for s,v in fb["sides"].items()},
  "frozen_at":"trained on 2026-05-01..2026-09-30, calibrated 2026-10-01..2026-11-03, evaluated once on 2026-11-04..2026-11-11",
  "fold_thresholds":{fn:{s:torch.load(DATA/f"bundle_{fn}.pt",weights_only=False)["sides"][s]["thresholds"] for s in ("LOW","HIGH")} for fn in ("WF_Jul","WF_Aug","WF_Sep","WF_Oct")},
  "teacher_v1_rules":RULES,"expert_order":W.EXPERTS,
  "load_note":"torch.load(path, weights_only=False); requires hype_early/train_walkforward.py (Norm, CortexEarly) and repo research/hype_local_only on PYTHONPATH"}
torch.save(bundle,R/"EARLY_LOCAL_MODEL_BUNDLE.pt")
# provenance
prov={"generated_local":metrics["generated_local"],"repo":"cryptobro1985-prog/pandora-testnet","branch":"research/hype-h1-local-v5-oi-microstructure-20261104",
 "repo_commit":os.popen("git -C /workspace/pandora-testnet rev-parse HEAD").read().strip(),
 "repo_artifacts_status":"v2: GitHub Actions artifacts downloaded with the owner's authenticated gh session (inventory in v2_extras.artifact_inventory of METRICS; 58 downloaded, 1 expired HTTP 410 HYPE-LOCAL-RAW-42624925967) + release hype-public-data-v1 assets. Used for: exact teacher alignment (project compact M1), local116 snapshot alignment, live WS receive-time audit, liquidation cross-check, project checkpoints forward scoring. No secrets copied.",
 "sources":{
  "trades":{"url":"https://public.bybit.com/trading/HYPEUSDT/HYPEUSDT{YYYY-MM-DD}.csv.gz","days":"2026-04-24..2026-11-11 (202 files)","use":"1s aggressor bars: price, buy/sell notional, counts, max trade"},
  "orderbook":{"url":"https://quote-saver.bycsi.com/orderbook/linear/HYPEUSDT/{date}_HYPEUSDT_ob200.data.zip","days":"202 days replayed","use":"1s causal L50 features (depth, imbalance, spread); raw deleted after processing"},
  "open_interest":{"url":"https://api.bybit.com/v5/market/open-interest (5min)","availability_rule":"value usable only 5 min after its stamp"},
  "holder_ratio":{"url":"https://api.bybit.com/v5/market/account-ratio (5min)","availability_rule":"usable 5 min after stamp"},
  "mark_index":{"url":"https://api.bybit.com/v5/market/mark-price-kline / index-price-kline (1m)","availability_rule":"usable at bar close"},
  "funding":{"url":"https://api.bybit.com/v5/market/funding/history","availability_rule":"usable at settlement time"},
  "liquidations":{"url":"https://api.cryptohftdata.com/v1/download?file=bybit/{YYYY-MM-DD}/{HH}/HYPEUSDT_liquidations.parquet (public, no key, 60 req/min)","status":"v2: used; causal by received_time; side SELL=long liquidated (verified: 97% of SELL events follow a negative 60s return)","hours":"see liq_alignment.json"}},
 "period_roles":{"2026-05..2026-06":"development/transfer (June never in repo plateau set)","2026-07..2026-10 (to 11-03)":"historical transfer folds - previously inspected by project, NOT pristine",
   "2026-11-04..2026-11-11":"post-freeze forward for THIS model (frozen before first look). Not live; the project may have seen part of this period as recent raw/live evidence."},
 "intermediate_hashes":{p.name:sha(p) for p in [DATA/"dataset.pkl",DATA/"teacher_continuous.json",DATA/"atlas.json"]},
 "feature_availability":FEATURE_AVAIL["by_month_family"]}
json.dump(prov,open(R/"DATA_PROVENANCE.json","w"),indent=1,default=float,ensure_ascii=False)
print("ok",[p.name for p in R.iterdir()])
