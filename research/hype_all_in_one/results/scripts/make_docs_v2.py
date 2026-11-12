"""Generate RU docs (report, phone summary, full summary+strategy) from v2 JSON outputs. Numbers only from files."""
import json
from pathlib import Path
D=Path('/workspace/data');R=Path('/workspace/pandora-testnet/research/hype_all_in_one/results')
VC=json.load(open(D/'version_comparison.json'));M=json.load(open(R/'EARLY_REAL_H1_LOCAL_METRICS.json'))
PC=json.load(open(D/'project_ckpt_forward.json'));AT=json.load(open(D/'atlas.json'))
LA=json.load(open(D/'liq_alignment.json'));LT=json.load(open(D/'latency_audit.json'))
V=['v1_public_bybit','v2a_aligned_no_liq','v2_aligned_plus_liq'];VN={'v1_public_bybit':'v1 (публичный Bybit)','v2a_aligned_no_liq':'v2a (выравнивание, без ликвидаций)','v2_aligned_plus_liq':'v2 (+ликвидации)'}
CN={'B0.4_SAFE_MAX_OOF_CAL':'≤0.40% SAFE (основной)','B0.7_SAFE_MAX_OOF_CAL':'≤0.70% SAFE','B1.0_SAFE_MAX_OOF_CAL':'≤1.00% SAFE','B99.0_SAFE_MAX_OOF_CAL':'без бюджета SAFE','B0.4_CAL_Q99':'≤0.40% агрессивный Q99','TEACHER_V1_same_episodes':'Учитель V1'}
def f(x,p=2,pct=False):
    if x is None:return '–'
    return f"{x*100:.1f}%" if pct else (f"{x:.{p}f}" if isinstance(x,float) else str(x))
def table(sec):
    o=['| Конфигурация | Версия | Сторона | Настоящих | Принято | TP | **False-first** | Precision | Coverage | Расст. мед, % | Задержка мед, с | Захват MFE |','|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for c,cn in CN.items():
        for v in (V if c!='TEACHER_V1_same_episodes' else ['v2_aligned_plus_liq']):
            x=VC[sec][v].get(c)
            if not x:continue
            for s in ('LOW','HIGH','COMBINED'):
                y=x[s];o.append(f"| {cn} | {VN[v] if c!='TEACHER_V1_same_episodes' else 'v2-лента'} | {s.replace('COMBINED','всего')} | {y['true_terminal_locals']} | {y['accepted']} | {y['tp']} | **{y['false_first']}** | {f(y['precision'],pct=True)} | {f(y['coverage'],pct=True)} | {f(y['median_dist_pct'])} | {f(y['median_delay_s'],0)} | {f(y['median_captured_mfe_ratio'])} |")
    return '\n'.join(o)
def ff_table():
    o=['| Конфигурация | Версия | Июль L/H | Авг L/H | Сен L/H | Окт L/H |','|---|---|---|---|---|---|']
    for c in list(CN)[:3]:
        for v in V:
            x=VC['fold_false_first'][v][c];o.append(f"| {CN[c]} | {VN[v]} | "+' | '.join(f"{x[fn]['LOW']}/{x[fn]['HIGH']}" for fn in ('WF_Jul','WF_Aug','WF_Sep','WF_Oct'))+' |')
    return '\n'.join(o)
def mfe_table():
    o=['| Система | Версия | Сделок | Gross Σ% | Net Σ% | Ложных PROTECT | Ложных REVERSE | Захват Local→Local |','|---|---|---:|---:|---:|---:|---:|---:|']
    for v in V:
        for k,x in VC['mfe_transfer'][v].items():
            o.append(f"| {k} | {VN[v]} | {f(x.get('n_trades'),0)} | {f(x.get('gross_pnl_pct_sum'),1)} | {f(x.get('net_pnl_pct_sum_fee0.11rt'),1)} | {f(x.get('false_protective_exits'),0)}/{f(x.get('protect_exits'),0)} | {f(x.get('false_full_reversals'),0)} | {f(x.get('net_local_to_local_capture_ratio'),pct=True)} |")
    return '\n'.join(o)
def pc_table():
    o=['| Чекпойнт проекта | Порог | Кандидатов | Принято (канд.) | TP | FP | LOW эп. прин/TP/FF | HIGH эп. прин/TP/FF |','|---|---:|---:|---:|---:|---:|---|---|']
    for r in PC['results']:
        c=r['candidate_level'];e=r['h1_episode_level']
        o.append(f"| {r['model']} | {r['threshold']:.3f} | {c['candidates']} | {c['accepted']} | {c['tp']} | {c['fp']} | {e['LOW']['accepted']}/{e['LOW']['true_first']}/{e['LOW']['false_first']} | {e['HIGH']['accepted']}/{e['HIGH']['true_first']}/{e['HIGH']['false_first']} |")
    return '\n'.join(o)
def liq_atlas():
    o=[]
    try:
        for side in ('LOW','HIGH'):
            S=AT['sides'][side] if 'sides' in AT else AT[side]
            rows=[]
            for kind,feats in S.items():
                if not isinstance(feats,dict):continue
                for k,v in feats.items():
                    if k.startswith('liq_') and isinstance(v,dict) and v.get('auc') is not None:rows.append((abs(v['auc']-.5),kind,k,v))
            rows.sort(reverse=True)
            o.append(f"**{side}** (топ по |AUC−0.5|):")
            for _,kind,k,v in rows[:8]:o.append(f"- {kind} `{k}`: AUC {v['auc']:.3f} ({'выше у TRUE' if v['auc']>.5 else 'выше у FALSE'}), n_true={v['n_true']}, n_false={v['n_false']}, стабильность знака: {v.get('sign_stable_months','–')}")
    except Exception as e:o.append(f"(atlas parse: {e})")
    return '\n'.join(o)
crit=M['success_criteria'];C=lambda k:'ПРОЙДЕН' if crit[k].get('pass') else 'НЕ ПРОЙДЕН'
TAB={'transfer':table('transfer_Jul_Oct'),'forward':table('forward_Nov4_11'),'ff':ff_table(),'mfe':mfe_table(),'pc':pc_table(),'liq':liq_atlas()}
json.dump({k:v for k,v in TAB.items()},open(D/'docs_tables.json','w'),ensure_ascii=False,indent=1)
for k,v in TAB.items(): open(D/f'docs_table_{k}.md','w').write(v)
print('tables ok; criteria',{k:crit[k].get('pass') for k in crit if k.startswith('C')})
