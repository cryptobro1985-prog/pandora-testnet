from __future__ import annotations
import json, os, threading, time
from flask import Flask, jsonify, Response
import requests

app=Flask(__name__)
REPO=os.getenv("STATUS_REPO","cryptobro1985-prog/pandora-testnet")
ISSUE=int(os.getenv("STATUS_ISSUE","24"))
TOKEN=os.getenv("TELEGRAM_BOT_TOKEN","")
_cache={"ts":0.0,"data":None}

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
@media(min-width:620px){.grid{grid-template-columns:repeat(4,1fr)}.card.wide{grid-column:span 2}.card.full{grid-column:1/-1}}
</style>
</head>
<body><div class="wrap">
<div class="hero"><div><div class="eyebrow">PANDORA · HYPE</div><div class="title">Caterpillar Quant</div><div class="sub" id="updated">Подключение…</div></div><div class="pulse"><i class="dot"></i><span id="live">LIVE</span></div></div>
<div class="grid">
<div class="card"><div class="k">Статус</div><div class="v cyan" id="status">—</div><div class="small" id="fresh">—</div></div>
<div class="card"><div class="k">Связи</div><div class="v" id="rels">0</div><div class="small"><span class="good" id="pos">+0</span> · <span class="bad" id="neg">−0</span></div></div>
<div class="card"><div class="k">Проверки</div><div class="v" id="checks">0</div><div class="small">ошибок <span id="errs">0</span></div></div>
<div class="card"><div class="k">MFE capture</div><div class="v" id="mfe">—</div><div class="bar"><div class="fill" id="mfebar"></div></div></div>
<div class="card wide"><div class="k">Активный Local</div><div class="v" id="local">WAIT</div><div class="row"><span>Confidence</span><b id="localconf">—</b></div><div class="row"><span>Stage</span><b id="localstage">—</b></div></div>
<div class="card wide"><div class="k">Quant</div><div class="row"><span>Labels</span><b id="qlabels">—</b></div><div class="row"><span>Champion</span><b id="champ">—</b></div><div class="row"><span>Last action</span><b id="qaction">—</b></div></div>
<div class="card wide"><div class="k">Гусеничка · PAPER</div><div class="row"><span>Equity</span><b id="equity">—</b></div><div class="row"><span>Return</span><b id="ret">—</b></div><div class="row"><span>Сделок / re-entry</span><b id="trades">—</b></div><div class="row"><span>Win rate</span><b id="wr">—</b></div><div class="row"><span>Max DD</span><b id="dd">—</b></div><div class="row"><span>Caterpillar vs straight</span><b id="delta">—</b></div></div>
<div class="card wide"><div class="k">Текущая позиция</div><div class="v amber" id="position">FLAT</div><div class="small" id="position2">—</div></div>
<div class="card full"><div class="k">Local models</div><div id="localmodels" class="small">—</div></div>
<div class="card full"><div class="k">Топ взаимосвязей</div><div id="toprels" class="small">Пока недостаточно labels</div></div>
<div class="card full"><div class="k">Ошибки обучения</div><div class="row"><span>Error rate</span><b id="erate">—</b></div><div class="row"><span>Prediction errors</span><b id="perrors">—</b></div></div>
</div><div class="footer">Research / PAPER only · автообновление 10 сек · реальные ордера отключены</div></div>
<script>
const el=id=>document.getElementById(id);
const n=(v,d=2)=>v==null?"—":Number(v).toLocaleString("ru-RU",{maximumFractionDigits:d});
const pct=(v,d=1)=>v==null?"—":(Number(v)*100).toFixed(d)+"%";
function render(s){
 el("status").textContent=s.status||"—";el("fresh").textContent="fresh "+n(s.freshness_seconds,0)+"s";
 el("rels").textContent=n(s.relationships_total,0);el("pos").textContent="+"+n(s.positive_relationships,0);el("neg").textContent="−"+n(s.negative_relationships,0);
 el("checks").textContent=n(s.prediction_checks,0);el("errs").textContent=n(s.errors_total,0);el("erate").textContent=pct(s.error_rate);el("perrors").textContent=JSON.stringify(s.prediction_errors||{});
 const p=s.paper||{},q=s.quant||{},l=s.active_local,m=p.mean_mfe_capture_ratio;
 el("mfe").textContent=pct(m);el("mfebar").style.width=Math.max(0,Math.min(100,(m||0)*100))+"%";
 if(l){el("local").textContent=l.side+" @ "+n(l.price,4);el("local").className="v "+(l.side==="LOW"?"good":"bad");el("localconf").textContent=pct(l.confidence);el("localstage").textContent=(l.stage||"—")+"s"}else{el("local").textContent="WAIT";el("local").className="v amber";el("localconf").textContent="—";el("localstage").textContent="—"}
 el("qlabels").textContent=n(q.labels,0);el("champ").textContent=q.champion_ready?"READY":"LEARNING";el("qaction").textContent=(q.last_action||{}).action||"FLAT";
 el("equity").textContent="$"+n(p.equity,2);el("ret").textContent=n(p.return_pct,2)+"%";el("trades").textContent=n(p.closed_trades,0)+" / "+n(p.reentries,0);el("wr").textContent=p.win_rate==null?"—":pct(p.win_rate);el("dd").textContent=n(p.max_drawdown_pct,2)+"%";el("delta").textContent=n(p.caterpillar_vs_straight_delta_pct,2)+" pp";
 const op=p.open_position;if(op){el("position").textContent=op.side;el("position").className="v "+(op.side==="LONG"?"good":"bad");el("position2").textContent="entry "+n(op.entry_price,4)+" · MFE "+pct(op.mfe)+" · MAE "+pct(op.mae)+" · "+op.leverage+"x · "+n(op.margin_fraction*100,1)+"% margin"}else{el("position").textContent="FLAT";el("position").className="v amber";el("position2").textContent="ждём подтверждённый local + edge"}
 const lm=s.local_models||{};el("localmodels").innerHTML=Object.entries(lm).map(([k,v])=>"<span class='tag'>"+k+" · "+(v.labels||0)+" labels · "+(v.positive||0)+" +</span>").join(" ")||"—";
 const top=(s.relationships||{}).top||[];el("toprels").innerHTML=top.slice(0,14).map(r=>"<div class='rel'><b>"+r.head+"</b> · "+r.feature+" · <span class='"+(r.weight>0?"good":"bad")+"'>"+n(r.weight,4)+"</span></div>").join("")||"Пока недостаточно labels";
 el("updated").textContent="обновлено "+new Date(s.updated_ts_ms||Date.now()).toLocaleTimeString("ru-RU");el("live").textContent=(s.freshness_seconds!=null&&s.freshness_seconds<180)?"LIVE":"STALE";
}
async function tick(){try{const r=await fetch("/api/status?x="+Date.now());const j=await r.json();if(j.error)throw Error(j.error);render(j)}catch(e){el("status").textContent="OFFLINE";el("updated").textContent=e.message}}
if(window.Telegram&&Telegram.WebApp){Telegram.WebApp.ready();Telegram.WebApp.expand();Telegram.WebApp.setHeaderColor("#05070b");Telegram.WebApp.setBackgroundColor("#05070b")}
tick();setInterval(tick,10000);
</script></body></html>'''

def parse_status(body:str):
    start=(body or "").find("{")
    end=(body or "").rfind("}")
    if start<0 or end<=start:return None
    return json.loads(body[start:end+1])

def fetch_status(force=False):
    now=time.time()
    if not force and _cache["data"] is not None and now-_cache["ts"]<5:return _cache["data"]
    try:
        r=requests.get("https://api.github.com/repos/"+REPO+"/issues/"+str(ISSUE),headers={"Accept":"application/vnd.github+json"},timeout=10)
        r.raise_for_status();data=parse_status(r.json().get("body",""))
        if not data:raise RuntimeError("status JSON not found")
        _cache.update(ts=now,data=data);return data
    except Exception as e:
        if _cache["data"] is not None:return _cache["data"]
        return {"status":"BOOTSTRAPPING","error":repr(e),"updated_ts_ms":int(now*1000)}

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

@app.get("/")
def index():return Response(HTML,mimetype="text/html")
@app.get("/api/status")
def status():return jsonify(fetch_status())
@app.get("/healthz")
def health():return jsonify({"ok":True,"issue":ISSUE})
@app.get("/api/telegram/setup")
def setup():telegram_setup();return jsonify({"ok":True})

threading.Thread(target=lambda:(time.sleep(3),telegram_setup()),daemon=True).start()
