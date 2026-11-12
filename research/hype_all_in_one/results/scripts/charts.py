import json,csv,numpy as np,matplotlib
matplotlib.use("Agg");import matplotlib.pyplot as plt
from pathlib import Path
R=Path("/workspace/pandora-testnet/research/hype_all_in_one/results")
M=json.load(open(R/"EARLY_REAL_H1_LOCAL_METRICS.json"))
pts=M["pareto_points_transfer"]
fig,ax=plt.subplots(1,2,figsize=(13,5.2))
for p in pts:
    if p["accepted"]==0:continue
    c=p["config"];col="red" if c=="TEACHER_V1" else ("tab:green" if "B0.4" in c else "tab:orange" if "B0.7" in c else "tab:blue" if "B1.0" in c else "gray")
    ax[0].scatter(p["false_first"],p["coverage"]*100,c=col,s=60 if c=="TEACHER_V1" else 25)
    if c=="TEACHER_V1" or "SAFE" in c:ax[0].annotate(c.replace("_SAFE_MAX_OOF_CAL"," SAFE"),(p["false_first"],p["coverage"]*100),fontsize=7)
ax[0].set_xlabel("false-first (transfer folds Jul-Oct, frozen thresholds)");ax[0].set_ylabel("coverage of true H1 Locals, %")
ax[0].set_title("Frozen detectors: false-first vs coverage\ngreen<=0.40% orange<=0.70% blue<=1.00% gray=no budget red=teacher")
for b,col in (("B0.4","tab:green"),("B0.7","tab:orange"),("B1.0","tab:blue")):
    l=M["oracle_frontier_DIAGNOSTIC_NOT_A_DETECTOR"][b]
    ax[1].plot([x["false_first"] for x in l],[x["coverage"]*100 for x in l],"o-",c=col,label=f"budget {b[1:]}%")
t=[p for p in pts if p["config"]=="TEACHER_V1"][0];ax[1].scatter([0],[t["coverage"]*100],c="red",s=80,label=f"teacher (median dist {t['median_dist_pct']:.2f}%)")
ax[1].set_xscale("symlog");ax[1].set_xlabel("false-first (log)");ax[1].set_ylabel("coverage %")
ax[1].set_title("ORACLE diagnostic: threshold swept ON TEST\n(upper bound, not a valid detector)");ax[1].legend(fontsize=8)
plt.tight_layout();plt.savefig(R/"PARETO_FRONTIER.png",dpi=130)
rows=list(csv.DictReader(open(R/"PER_LOCAL_ENTRY_DISTANCE.csv")))
def fl(k):return [float(r[k]) for r in rows if r[k] not in ("","None")]
fig,ax=plt.subplots(figsize=(11,5))
bins=np.linspace(0,7,57)
ax.hist(fl("first_0.25pct_anchor_dist"),bins,alpha=.4,label="first 0.25% anchor (lower bound, every Local)")
ax.hist(fl("teacher_dist_pct"),bins,alpha=.6,label=f"teacher V1 entry (n={len(fl('teacher_dist_pct'))})",color="red")
e=[float(r["B0.4_dist_pct"]) for r in rows if r["B0.4_outcome"]=="TRUE_FIRST"]
e2=[float(r["B1.0_dist_pct"]) for r in rows if r["B1.0_outcome"]=="TRUE_FIRST"]
ax.hist(e,bins,alpha=.9,label=f"early B0.4 true-first (n={len(e)})",color="green");ax.hist(e2,bins,alpha=.7,label=f"early B1.0 true-first (n={len(e2)})",color="blue")
ax.set_xlabel("entry distance from exact H1 extreme, %");ax.set_ylabel("count of true Locals");ax.legend()
ax.set_title(f"Entry distance per true H1 Local (Jul-Nov, {len(rows)} Locals)")
plt.tight_layout();plt.savefig(R/"ENTRY_DISTANCE_PER_LOCAL.png",dpi=130);print("ok")
