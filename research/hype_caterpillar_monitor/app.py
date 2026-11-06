from __future__ import annotations
import json, os, threading, time, re
from flask import Flask, jsonify, Response, request
import requests

app=Flask(__name__)
app.config["MAX_CONTENT_LENGTH"]=262144
REPO=os.getenv("STATUS_REPO","cryptobro1985-prog/pandora-testnet")
ISSUE=int(os.getenv("STATUS_ISSUE","24"))
TOKEN=os.getenv("TELEGRAM_BOT_TOKEN","")
_cache={"ts":0.0,"data":None,"source":None,"ingest_ts":0.0,"github_ts":0.0,"v2_seen":False,"preferred_run_id":0}
GITHUB_POLL_SECONDS=float(os.getenv("GITHUB_POLL_SECONDS","90"))

HTML=r'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#05070b">
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<title>HYPE Caterpillar Quant</title>
<style>
:root{--bg:#05070b;--card:#0d1118;--line:#1d2938;--text:#edf6ff;--muted:#71829b;--cyan:#51f6ff;--green:#55f59a;--red:#ff6b78;--amber:#ffc857}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 50% -10%,#0d2432 0,#05070b 38%);color:var(--text);font-family:Inter,system-ui,-apple-system,sans-serif;min-height:100vh}
.wrap{max-width:760px;margin:auto;padding:18px 14px 40px}.hero{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:16px}.eyebrow{font-size:11px;letter-spacing:.18em;color:var(--cyan);font-weight:800}.title{font-size:25px;font-weight:900;line-height:1.05;margin:5px 0}.sub{color:var(--muted);font-size:12px}
.pulse{display:flex;gap:7px;align-items:center;font-size:12px;color:var(--green);font-weight:800}.dot{width:9px;height:9px;background:var(--green);border-radius:50%;box-shadow:0 0 16px var(--green);animation:p 1.4s infinite}@keyframes p{50%{opacity:.35}}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}.card{background:linear-gradient(145deg,rgba(17,24,36,.95),rgba(8,12,18,.96));border:1px solid var(--line);border-radius:16px;padding:14px}.card.wide{grid-column:1/-1}.k{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.12em;font-weight:800}.v{font-size:25px;font-weight:900;margin-top:5px}.small{font-size:12px;color:var(--muted);margin-top:5px}.good{color:var(--green)}.bad{color:var(--red)}.cyan{color:var(--cyan)}.amber{color:var(--amber)}
.row{display:flex;justify-content:space-between;gap:12px;padding:8px 0;border-bottom:1px solid rgba(255,255,255,.055);font-size:13px}.row:last-child{border:0}.row span:first-child{color:var(--muted)}.row b{text-align:right;overflow-wrap:anywhere}.bar{height:6px;background:#09101a;border-radius:9px;overflow:hidden;margin-top:9px}.fill{height:100%;background:linear-gradient(90deg,var(--cyan),var(--green));border-radius:9px;transition:width .5s}.tag{display:inline-block;padding:4px 7px;border-radius:8px;background:#0b2831;color:var(--cyan);font-size:10px;font-weight:800;margin:2px}.rel{font-size:11px;padding:6px 0;border-bottom:1px solid rgba(255,255,255,.04)}.footer{text-align:center;color:#516177;font-size:10px;margin-top:16px}
.busgrid{display:grid;grid-template-columns:repeat(29,1fr);gap:3px;margin-top:11px}.bit{height:7px;border-radius:3px;background:#101923;box-shadow:inset 0 0 0 1px rgba(255,255,255,.03);transition:background .25s,box-shadow .25s,transform .25s}.bit.seen{background:#184d39}.bit.target{background:#4d3b18}.bit.meta{background:#263142}.bit.missing{background:#4d1d24}.bit.hot{background:var(--cyan);box-shadow:0 0 10px rgba(81,246,255,.7);transform:scaleY(1.35)}.triplet{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:10px}.mini{background:#080d14;border:1px solid rgba(255,255,255,.05);border-radius:10px;padding:9px}.mini b{display:block;font-size:16px;margin-top:3px}.feed{max-height:150px;overflow:hidden;margin-top:8px;font:11px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace}.feedline{padding:4px 0;border-bottom:1px solid rgba(255,255,255,.04);color:#9bb0c8}.feedline strong{color:var(--green)}.scan{height:2px;background:linear-gradient(90deg,transparent,var(--cyan),transparent);animation:scan 1.7s linear infinite;margin-top:10px;opacity:.85}@keyframes scan{0%{transform:translateX(-40%)}100%{transform:translateX(40%)}}
@media(min-width:620px){.grid{grid-template-columns:repeat(4,1fr)}.card.wide{grid-column:span 2}.card.full{grid-column:1/-1}}
</style>
</head>
<body><div class="wrap">
<div class="hero"><div><div class="eyebrow">PANDORA · HYPE</div><div class="title">Caterpillar Quant</div><div class="sub" id="updated">Подключение…</div><div class="small">UI v4 · CORTEX 20B · Fibonacci · Learned Entry</div></div><div class="pulse"><i class="dot"></i><span id="live">LIVE</span></div></div>
<div class="grid">
<div class="card"><div class="k">Статус</div><div class="v cyan" id="status">—</div><div class="small" id="fresh">—</div></div>
<div class="card"><div class="k">Связи</div><div class="v" id="rels">0</div><div class="small"><span class="good" id="pos">+0</span> · <span class="bad" id="neg">−0</span></div></div>
<div class="card"><div class="k">Проверки</div><div class="v" id="checks">0</div><div class="small">ошибок <span id="errs">0</span></div></div>
<div class="card"><div class="k">MFE capture</div><div class="v" id="mfe">—</div><div class="bar"><div class="fill" id="mfebar"></div></div></div>
<div class="card wide"><div class="k">Активный Local</div><div class="v" id="local">WAIT</div><div class="row"><span>Confidence</span><b id="localconf">—</b></div><div class="row"><span>Stage</span><b id="localstage">—</b></div><div class="row"><span>Source</span><b id="localsource">—</b></div><div class="row"><span>Policy</span><b id="policy">—</b></div><div class="small" id="localwhy">—</div></div>
<div class="card wide"><div class="k">Quant</div><div class="row"><span>All labels</span><b id="qlabels">—</b></div><div class="row"><span>v2 labels</span><b id="qv2labels">—</b></div><div class="row"><span>Champion</span><b id="champ">—</b></div><div class="row"><span>Last action</span><b id="qaction">—</b></div></div>
<div class="card wide"><div class="k">Quant + CORTEX 20B · LOCAL</div><div class="row"><span>Status</span><b id="astatus">—</b></div><div class="row"><span>Model / backend</span><b id="amodel">—</b></div><div class="row"><span>Decision / confidence</span><b id="adecision">—</b></div><div class="row"><span>24h training</span><b id="atrain">0%</b></div><div class="bar"><div class="fill" id="atrainbar"></div></div><div class="row"><span>Elapsed / evidence</span><b id="atrainparts">—</b></div><div class="row"><span>Decisions / matured</span><b id="acalls">—</b></div><div class="row"><span>Learning memory</span><b id="amemory">—</b></div><div class="row"><span>Directional accuracy</span><b id="aacc">—</b></div><div class="row"><span>US session now</span><b id="asession">—</b></div><div class="row"><span>Parallel lanes</span><b id="aparallel">—</b></div><div class="row"><span>Regime</span><b id="aregime">—</b></div><div class="small"><b>Текущая гипотеза:</b> <span id="athesis">—</span></div><div class="small"><b>За:</b> <span id="afor">—</span></div><div class="small"><b>Против:</b> <span id="aagainst">—</span></div><div class="small"><b>Инвалидация:</b> <span id="ainvalidation">—</span></div><div class="small"><b>Разбор последнего решения:</b> <span id="acritique">—</span></div><div class="small">24h progress = зрелость evidence, а не обещание точности/прибыли. Показывается audit summary, не скрытая chain-of-thought.</div></div>
<div class="card wide"><div class="k">US market behavior · HYPE</div><div class="row"><span>Premarket</span><b id="uspremarket">—</b></div><div class="row"><span>Cash 09:30–16:00 ET</span><b id="uscash">—</b></div><div class="row"><span>After-hours</span><b id="usafter">—</b></div><div class="row"><span>Overnight</span><b id="usovernight">—</b></div><div class="small">Сравнение фактической волатильности, directional accuracy и net expectancy по дозревшим 60/180/300s эпизодам.</div></div>
<div class="card wide"><div class="k">Fibonacci · Local ↔ Local learning</div><div class="row"><span>Training</span><b id="fibtrain">0%</b></div><div class="bar"><div class="fill" id="fibbar"></div></div><div class="row"><span>Swing</span><b id="fibswing">—</b></div><div class="row"><span>Closest level</span><b id="fibclosest">—</b></div><div class="row"><span>Touches / matured / pending</span><b id="fibcounts">—</b></div><div class="small" id="fiblevels">Ждём первую подтверждённую пару Local Low ↔ Local High.</div><div class="small">Проверяем 0.236 / 0.382 / 0.5 / 0.618 / 0.786 / 1.0 и extensions 1.272 / 1.618. Фибо обучается как causal feature и отдельный continuation/reversal head, а не как жёсткий сигнал.</div></div>
<div class="card wide"><div class="k">116-point data bus</div><div class="triplet"><div class="mini"><span class="k">Inputs seen</span><b id="inputseen">—</b></div><div class="mini"><span class="k">Snapshots</span><b id="sampled">—</b></div><div class="mini"><span class="k">Micro rows</span><b id="micro">—</b></div></div><div class="row"><span>Data status</span><b id="datastatus">—</b></div><div class="busgrid" id="bus"></div><div class="scan"></div><div class="small">зелёный = input/quality был получен · жёлтый = target/eval · серый = metadata · красный = input ещё не виделся</div></div>
<div class="card wide"><div class="k">Готовность обучения</div><div class="v cyan" id="learnpct">0%</div><div class="small" id="learnstatus">COLLECTING</div><div class="row"><span>Local</span><b id="plocal">0%</b></div><div class="row"><span>Bounce</span><b id="pbounce">0%</b></div><div class="row"><span>Entry</span><b id="pentry">0%</b></div><div class="row"><span>Exit</span><b id="pexit">0%</b></div><div class="row"><span>Re-entry</span><b id="preentry">0%</b></div><div class="row"><span>Fibonacci</span><b id="pfib">0%</b></div><div class="small">Entry обучается на виртуальных кандидатах; PAPER не обязан терять деньги ради обучения.</div></div>
<div class="card wide"><div class="k">Local ↔ Local · causal reference</div><div class="row"><span>H1 bars</span><b id="hbars">—</b></div><div class="row"><span>Strict pivots</span><b id="hpivots">—</b></div><div class="row"><span>Closed legs</span><b id="hlegs">—</b></div><div class="row"><span>1x return</span><b id="href1">—</b></div><div class="row"><span>20% × 25x reference</span><b id="hrefcfg">—</b></div><div class="small">Causal H1 confirmation reference; не прогноз прибыли, liquidation/slippage отдельно.</div></div>
<div class="card wide"><div class="k">Гусеничка · PAPER v4</div><div class="row"><span>Policy</span><b id="policyver">—</b></div><div class="row"><span>Equity</span><b id="equity">—</b></div><div class="row"><span>Return</span><b id="ret">—</b></div><div class="row"><span>Сделок / re-entry</span><b id="trades">—</b></div><div class="row"><span>Win rate</span><b id="wr">—</b></div><div class="row"><span>Max DD</span><b id="dd">—</b></div><div class="row"><span>Entry model</span><b id="entrymodel">—</b></div><div class="row"><span>Legacy PAPER</span><b id="legacypaper">—</b></div><div class="small">Новая версия не торгует вслепую при подтверждении local: сначала учится на виртуальных entry-кандидатах.</div></div>
<div class="card wide"><div class="k">Quant + CORTEX 20B · PAPER</div><div class="row"><span>Equity</span><b id="aequity">—</b></div><div class="row"><span>Return</span><b id="aret">—</b></div><div class="row"><span>Trades</span><b id="atrades">—</b></div><div class="row"><span>Win rate</span><b id="awr">—</b></div><div class="row"><span>Max DD</span><b id="add">—</b></div><div class="row"><span>Δ vs Quant</span><b id="adelta">—</b></div><div class="row"><span>Position</span><b id="aposition">FLAT</b></div></div>
<div class="card wide"><div class="k">Текущая позиция</div><div class="v amber" id="position">FLAT</div><div class="small" id="position2">—</div></div>
<div class="card full"><div class="k">Local / Caterpillar models</div><div id="localmodels" class="small">—</div><div class="row"><span>Exit labels</span><b id="exitlabels">—</b></div><div class="row"><span>Re-entry labels</span><b id="relabels">—</b></div></div>
<div class="card full"><div class="k">Топ взаимосвязей</div><div id="toprels" class="small">Пока недостаточно labels</div></div>
<div class="card full"><div class="k">Ошибки обучения</div><div class="row"><span>Error rate</span><b id="erate">—</b></div><div class="row"><span>Prediction errors</span><b id="perrors">—</b></div></div>
<div class="card full"><div class="k">Live activity</div><div id="feed" class="feed"><div class="feedline">ожидаю первый snapshot…</div></div></div>
</div><div class="footer">Research / PAPER only · direct push + резерв GitHub · UI heartbeat 3 сек · реальные ордера отключены</div></div>
<script>
const el=id=>document.getElementById(id);
const n=(v,d=2)=>v==null?"—":Number(v).toLocaleString("ru-RU",{maximumFractionDigits:d});
const pct=(v,d=1)=>v==null?"—":(Number(v)*100).toFixed(d)+"%";
let lastSnapshot=null,lastUpdated=null;
const feed=[];
const bus=el("bus");
for(let i=0;i<116;i++){const b=document.createElement("i");b.className="bit";b.title="Point "+(i+1);bus.appendChild(b)}
function addFeed(msg){
 const t=new Date().toLocaleTimeString("ru-RU");
 feed.unshift("<div class='feedline'><strong>"+t+"</strong> · "+msg+"</div>");
 if(feed.length>8)feed.pop();
 el("feed").innerHTML=feed.join("");
}
function pulseBus(){
 const bits=[...document.querySelectorAll(".bit")];
 bits.forEach((b,i)=>{setTimeout(()=>{b.classList.add("hot");setTimeout(()=>b.classList.remove("hot"),380)},(i%29)*18+Math.floor(i/29)*70)});
}
function render(s){
 el("status").textContent=s.status||"—";el("fresh").textContent="fresh "+n(s.freshness_seconds,0)+"s";
 el("rels").textContent=n(s.relationships_total,0);el("pos").textContent="+"+n(s.positive_relationships,0);el("neg").textContent="−"+n(s.negative_relationships,0);
 el("checks").textContent=n(s.prediction_checks,0);el("errs").textContent=n(s.errors_total,0);el("erate").textContent=pct(s.error_rate);el("perrors").textContent=JSON.stringify(s.prediction_errors||{});
 const p=s.paper||{},q=s.quant||{},a=s.astra||{},ap=s.astra_paper||{},ad=a.last_decision||{},ac=a.last_critique||{},l=s.active_local,m=p.mean_mfe_capture_ratio,tp=s.training_progress||{},sh=s.structural_history||{},fib=s.fibonacci||{},fibcur=fib.current||{},em=s.entry_model||{},legacy=s.legacy_paper_archive||{};
 const fc=s.feature_contract||{},seen=new Set(fc.seen_input_ids||[]),targets=new Set(fc.target_eval_ids||[]),meta=new Set(fc.metadata_ids||[]);
 const inputTotal=(fc.supported_input_ids||[]).length,inputSeen=Number(fc.seen_input_count||0);
 el("inputseen").textContent=n(inputSeen,0)+" / "+n(inputTotal,0);el("datastatus").textContent=(inputTotal>0&&inputSeen===inputTotal)?"ГОТОВО":"СБОР";
 const ready=v=>Number(v||0)>=100?"ГОТОВО":("ОБУЧЕНИЕ "+n(v,1)+"%");
 el("learnpct").textContent=Number(tp.overall_percent||0)>=100?"ГОТОВО":n(tp.overall_percent,1)+"%";el("learnstatus").textContent=tp.status||"COLLECTING_LABELS";
 const th=tp.heads||{};el("plocal").textContent=ready((th.local||{}).percent);el("pbounce").textContent=ready((th.bounce||{}).percent);el("pentry").textContent=ready((th.entry||{}).percent);el("pexit").textContent=ready((th.exit||{}).percent);el("preentry").textContent=ready((th.reentry||{}).percent);el("pfib").textContent=ready((th.fibonacci||{}).percent);
 el("hbars").textContent=n(sh.bars_loaded,0);el("hpivots").textContent=n(sh.strict_pivots,0);el("hlegs").textContent=n(sh.closed_legs,0);el("href1").textContent=n(sh.return_1x_pct,2)+"%";el("hrefcfg").textContent=n(sh.return_configured_reference_pct,2)+"%";
 el("sampled").textContent=n(s.sampled_states,0);el("micro").textContent=n(s.processed_micro_rows,0);
 [...document.querySelectorAll(".bit")].forEach((b,i)=>{const id=i+1;b.className="bit "+(seen.has(id)?"seen":targets.has(id)?"target":meta.has(id)?"meta":"missing")});
 el("mfe").textContent=pct(m);el("mfebar").style.width=Math.max(0,Math.min(100,(m||0)*100))+"%";
 if(l){el("local").textContent="ГОТОВО · "+l.side+" @ "+n(l.price,4);el("local").className="v "+(l.side==="LOW"?"good":"bad");el("localconf").textContent=pct(l.confidence);el("localstage").textContent=l.stage===0?"STRICT H1":((l.stage||"—")+"s");el("localsource").textContent=l.source||"—";const e=l.evidence||{};el("localwhy").textContent=(e.rule||"H1")+" · L"+n(e.left_hours,0)+"/K"+n(e.right_hours,0)+" · pivot H/L "+n(e.pivot_high,4)+"/"+n(e.pivot_low,4)+" · next2 H/L "+n(e.future_high_max,4)+"/"+n(e.future_low_min,4)}else{el("local").textContent="WAIT";el("local").className="v amber";el("localconf").textContent="—";el("localstage").textContent="—";el("localsource").textContent="—";el("localwhy").textContent="—"}el("policy").textContent=s.policy_state||"—";
 el("qlabels").textContent=n(q.labels,0);el("qv2labels").textContent=n(q.v2_labels,0);el("champ").textContent=q.champion_ready?"READY":"LEARNING";el("qaction").textContent=(q.last_action||{}).action||"FLAT";
 el("astatus").textContent=a.state||"—";el("amodel").textContent=(a.model||"—")+" · "+(a.backend||"—")+" · "+(a.reasoning_effort||"—");
 el("adecision").textContent=(ad.decision||"—")+" / "+(ad.confidence==null?"—":pct(ad.confidence));
 const at=a.training_progress||{};el("atrain").textContent=n(at.overall_percent,1)+"%";el("atrainbar").style.width=Math.max(0,Math.min(100,Number(at.overall_percent||0)))+"%";
 el("atrainparts").textContent=n(at.elapsed_percent,1)+"% time · "+n(at.evidence_percent,1)+"% evidence";
 el("acalls").textContent=n(a.calls,0)+" / "+n(a.matured_episodes,0);el("amemory").textContent=n(a.memory_episodes,0)+" · pending "+n(a.pending_episodes,0);
 el("aacc").textContent=pct(a.directional_accuracy);el("asession").textContent=a.current_us_session||ad.us_market_session||"—";const rc=s.runtime_concurrency||{};el("aparallel").textContent="Quant "+n(rc.quant_loop,0)+" · Cortex "+n(rc.cortex_workers,0)+"×"+n(rc.cortex_cpu_threads,0)+"T · I/O "+n(rc.io_workers,0);el("aregime").textContent=ad.market_regime||"—";
 const us=a.us_session_stats||{};const usfmt=x=>{const z=us[x]||{};return n(z.matured,0)+" ep · acc "+pct(z.directional_accuracy)+" · net "+pct(z.mean_directional_net)+" · |move| "+pct(z.mean_abs_return)};
 el("uspremarket").textContent=usfmt("US_PREMARKET");el("uscash").textContent=usfmt("US_CASH");el("usafter").textContent=usfmt("US_AFTER_HOURS");el("usovernight").textContent=usfmt("US_OVERNIGHT");
 el("fibtrain").textContent=n(fib.training_percent,1)+"%";el("fibbar").style.width=Math.max(0,Math.min(100,Number(fib.training_percent||0)))+"%";
 const fs=fibcur.swing_from||{},ft=fibcur.swing_to||{},fcx=fibcur.closest||{};
 el("fibswing").textContent=fibcur.available?((fs.side||"—")+" "+n(fs.price,4)+" → "+(ft.side||"—")+" "+n(ft.price,4)):"—";
 el("fibclosest").textContent=fibcur.available?((fcx.name||"—")+" @ "+n(fcx.price,4)+" · "+n(fcx.distance_bps,1)+" bps"):"—";
 const flevels=fib.levels||{};const ftouches=Object.values(flevels).reduce((z,x)=>z+Number((x||{}).touches||0),0);const fmatured=Object.values(flevels).reduce((z,x)=>z+Number((x||{}).matured||0),0);
 el("fibcounts").textContent=n(ftouches,0)+" / "+n(fmatured,0)+" / "+n(fib.pending,0);
 el("fiblevels").innerHTML=Object.entries(flevels).map(([k,v])=>"<span class='tag'>"+k+" · n "+n(v.matured,0)+" · cont "+pct(v.continuation_rate)+" · rev "+pct(v.reversal_rate)+" · net "+pct(v.mean_net)+"</span>").join(" ")||"Ждём касания уровней.";
 el("athesis").textContent=ad.thesis||"—";el("afor").textContent=(ad.evidence_for||[]).join(" · ")||"—";el("aagainst").textContent=(ad.evidence_against||[]).join(" · ")||"—";
 el("ainvalidation").textContent=ad.invalidation||"—";el("acritique").textContent=(ac.lesson||"—")+(ac.horizon_s?" · "+ac.horizon_s+"s":"");
 el("policyver").textContent="v"+n(s.policy_contract_version,0);el("equity").textContent="$"+n(p.equity,2);el("ret").textContent=n(p.return_pct,2)+"%";el("trades").textContent=n(p.closed_trades,0)+" / "+n(p.reentries,0);el("wr").textContent=p.win_rate==null?"—":pct(p.win_rate);el("dd").textContent=n(p.max_drawdown_pct,2)+"%";
 const elabs=em.labels||{};el("entrymodel").textContent=(em.ready?"READY":"LEARNING")+" · 60/180/300 "+n(elabs["60"]??elabs[60],0)+"/"+n(elabs["180"]??elabs[180],0)+"/"+n(elabs["300"]??elabs[300],0);
 el("legacypaper").textContent=legacy.return_pct==null?"—":n(legacy.return_pct,2)+"% · "+n(legacy.closed_trades,0)+" trades";
 el("aequity").textContent="$"+n(ap.equity,2);el("aret").textContent=n(ap.return_pct,2)+"%";el("atrades").textContent=n(ap.closed_trades,0);el("awr").textContent=ap.win_rate==null?"—":pct(ap.win_rate);el("add").textContent=n(ap.max_drawdown_pct,2)+"%";el("adelta").textContent=n(s.astra_vs_quant_delta_pct,2)+" pp";
 const aop=ap.open_position;el("aposition").textContent=aop?(Number(aop.side)>0?"LONG":"SHORT")+" · "+n(Number(aop.current_return||0)*100,2)+"%":"FLAT";
 const op=p.open_position;if(op){el("position").textContent=op.side;el("position").className="v "+(op.side==="LONG"?"good":"bad");el("position2").textContent="entry "+n(op.entry_price,4)+" · MFE "+pct(op.mfe)+" · MAE "+pct(op.mae)+" · "+op.leverage+"x · "+n(op.margin_fraction*100,1)+"% margin"}else{el("position").textContent="FLAT";el("position").className="v amber";el("position2").textContent="ждём подтверждённый local + edge"}
 const lm=s.local_models||{},bm=s.bounce_models||{};el("localmodels").innerHTML=[...Object.entries(lm).map(([k,v])=>"<span class='tag'>STRICT "+k+" · "+(v.labels||0)+" / "+(v.positive||0)+"+</span>"),...Object.entries(bm).map(([k,v])=>"<span class='tag'>BOUNCE "+k+" · "+(v.labels||0)+" / "+(v.positive||0)+"+</span>")].join(" ")||"—";el("exitlabels").textContent=n((s.exit_model||{}).labels,0);el("relabels").textContent=n((s.reentry_model||{}).labels,0);
 const top=(s.relationships||{}).top||[];el("toprels").innerHTML=top.slice(0,14).map(r=>"<div class='rel'><b>"+r.head+"</b> · "+r.feature+" · <span class='"+(r.weight>0?"good":"bad")+"'>"+n(r.weight,4)+"</span></div>").join("")||"Пока недостаточно labels";
 const age=s.stream_age_seconds==null?s.freshness_seconds:s.stream_age_seconds;
 const direct=s.transport==="DIRECT_PUSH";
 el("updated").textContent="данные "+new Date(s.updated_ts_ms||Date.now()).toLocaleTimeString("ru-RU")+" · "+(direct?"DIRECT":"GITHUB")+" · канал "+n(age,0)+"s";
 el("live").textContent=(age!=null&&age<45)?"LIVE":(age!=null&&age<180?"STALE":"RECONNECT");
 if(lastUpdated!==s.updated_ts_ms){
   const prev=lastSnapshot||{};
   const ds=Number(s.sampled_states||0)-Number(prev.sampled_states||0), dm=Number(s.processed_micro_rows||0)-Number(prev.processed_micro_rows||0);
   const dq=Number(q.labels||0)-Number((prev.quant||{}).labels||0);
   const act=(q.last_action||{}).action||"FLAT";
   const acalls=Number(a.calls||0),prevAcalls=Number((prev.astra||{}).calls||0);
   addFeed("snapshot "+n(s.sampled_states,0)+" · micro +"+Math.max(0,dm)+" · labels "+n(q.labels,0)+(dq>0?" (+"+dq+")":"")+" · action "+act+(acalls>prevAcalls?" · CORTEX "+(ad.decision||"—"):""));
   pulseBus();lastUpdated=s.updated_ts_ms;lastSnapshot=s;
 }
}
async function tick(){try{const r=await fetch("/api/status?x="+Date.now(),{cache:"no-store"});const j=await r.json();if(!r.ok)throw Error(j.error||("HTTP "+r.status));render(j)}catch(e){el("live").textContent="RECONNECT";el("updated").textContent="канал переподключается · "+e.message}}
if(window.Telegram&&Telegram.WebApp){Telegram.WebApp.ready();Telegram.WebApp.expand();Telegram.WebApp.setHeaderColor("#05070b");Telegram.WebApp.setBackgroundColor("#05070b")}
tick();setInterval(tick,3000);
</script></body></html>'''

def parse_status(body:str):
    start=(body or "").find("{")
    end=(body or "").rfind("}")
    if start<0 or end<=start:return None
    return json.loads(body[start:end+1])

def _decorate(data,source):
    out=dict(data or {})
    now=time.time()
    received=_cache["ingest_ts"] if source=="direct" else _cache["ts"]
    out["transport"]="DIRECT_PUSH" if source=="direct" else "GITHUB_FALLBACK"
    out["server_received_ts_ms"]=int(received*1000) if received else None
    out["stream_age_seconds"]=max(0.0,now-received) if received else None
    return out

def fetch_status(force=False):
    now=time.time()
    if _cache["data"] is not None and _cache["source"]=="direct" and now-_cache["ingest_ts"]<120:
        return _decorate(_cache["data"],"direct")
    if not force and _cache["data"] is not None and now-_cache["github_ts"]<GITHUB_POLL_SECONDS:
        return _decorate(_cache["data"],_cache["source"] or "github")
    _cache["github_ts"]=now
    try:
        r=requests.get(
            "https://api.github.com/repos/"+REPO+"/issues/"+str(ISSUE),
            headers={"Accept":"application/vnd.github+json","User-Agent":"hype-caterpillar-monitor/2.0"},
            timeout=10,
        )
        r.raise_for_status();data=parse_status(r.json().get("body",""))
        if not data:raise RuntimeError("status JSON not found")
        if _cache["source"]!="direct" or now-_cache["ingest_ts"]>=120:
            _cache.update(ts=now,data=data,source="github")
        return _decorate(_cache["data"],_cache["source"] or "github")
    except Exception as e:
        if _cache["data"] is not None:
            out=_decorate(_cache["data"],_cache["source"] or "github")
            out["transport_warning"]=repr(e)
            return out
        return {"status":"BOOTSTRAPPING","transport":"WAITING_FOR_DIRECT_PUSH","transport_warning":repr(e),"updated_ts_ms":int(now*1000),"stream_age_seconds":None}

def telegram_setup():
    if not TOKEN:return
    host=os.getenv("RENDER_EXTERNAL_HOSTNAME")
    url=os.getenv("MINIAPP_URL") or ("https://"+host+"/" if host else None)
    if not url:return
    api="https://api.telegram.org/bot"+TOKEN
    try:
        requests.post(api+"/setChatMenuButton",json={"menu_button":{"type":"web_app","text":"HYPE Monitor","web_app":{"url":url}}},timeout=15)
        requests.post(api+"/setMyDescription",json={"description":"HYPE Caterpillar Quant — live learning monitor"},timeout=15)
        requests.post(api+"/setMyShortDescription",json={"short_description":"HYPE Quant live monitor"},timeout=15)
    except Exception:pass

@app.after_request
def no_cache(resp):
    resp.headers["Cache-Control"]="no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"]="no-cache"
    resp.headers["Expires"]="0"
    return resp

@app.get("/")
def index():return Response(HTML,mimetype="text/html")
@app.get("/api/status")
def status():return jsonify(fetch_status())

@app.post("/api/ingest")
def ingest():
    if request.headers.get("X-Caterpillar-Research")!="1":
        return jsonify({"ok":False,"error":"research header required"}),403
    data=request.get_json(silent=True)
    if not isinstance(data,dict) or data.get("research_only") is not True or data.get("real_orders") is not False:
        return jsonify({"ok":False,"error":"invalid research payload"}),400
    sha=str(data.get("github_sha") or "")
    run_id=str(data.get("github_run_id") or "")
    if not re.fullmatch(r"[0-9a-f]{40}",sha) or not run_id.isdigit():
        return jsonify({"ok":False,"error":"invalid run identity"}),400
    updated=data.get("updated_ts_ms")
    try: updated=float(updated)
    except Exception:return jsonify({"ok":False,"error":"missing updated_ts_ms"}),400
    now_ms=time.time()*1000
    if updated>now_ms+300000 or updated<now_ms-900000:
        return jsonify({"ok":False,"error":"stale status payload"}),400
    is_v2=(data.get("local_target") in ("STRICT_H1_L6_K2","FULL_HISTORY_STRICT_H1_L6_K2"))
    if _cache.get("v2_seen") and not is_v2:
        return jsonify({"ok":False,"error":"legacy policy payload ignored"}),409
    run_int=int(run_id)
    if is_v2:
        preferred=int(_cache.get("preferred_run_id") or 0)
        if preferred and run_int<preferred:
            return jsonify({"ok":False,"error":"older v2 run ignored","preferred_run_id":preferred}),409
        _cache["v2_seen"]=True
        _cache["preferred_run_id"]=max(preferred,run_int)
    now=time.time()
    _cache.update(ts=now,data=data,source="direct",ingest_ts=now)
    return jsonify({"ok":True,"received_ts_ms":int(now*1000)})

@app.get("/healthz")
def health():
    now=time.time();age=None if not _cache["ingest_ts"] else max(0.0,now-_cache["ingest_ts"])
    return jsonify({"ok":True,"issue":ISSUE,"source":_cache["source"],"direct_age_seconds":age})
@app.get("/api/telegram/setup")
def setup():telegram_setup();return jsonify({"ok":True})

threading.Thread(target=lambda:(time.sleep(3),telegram_setup()),daemon=True).start()
