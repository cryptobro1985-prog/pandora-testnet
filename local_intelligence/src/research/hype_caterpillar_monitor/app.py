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
<title>HYPE Local Engine</title>
<style>
:root{--bg:#05070b;--card:#0c121a;--line:#1c2a3b;--text:#eef7ff;--muted:#7f91aa;--cyan:#55efff;--green:#57f59b;--red:#ff6677;--amber:#ffc857}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 50% -15%,#0c2937 0,#05070b 40%);color:var(--text);font-family:Inter,system-ui,-apple-system,sans-serif;min-height:100vh}
.wrap{max-width:840px;margin:auto;padding:18px 14px 42px}.hero{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:15px}.eyebrow{font-size:11px;letter-spacing:.18em;color:var(--cyan);font-weight:900}.title{font-size:26px;font-weight:950;line-height:1.05;margin:5px 0}.sub{color:var(--muted);font-size:12px}
.pulse{display:flex;gap:7px;align-items:center;font-size:12px;color:var(--green);font-weight:900}.dot{width:9px;height:9px;border-radius:50%;background:var(--green);box-shadow:0 0 16px var(--green);animation:p 1.3s infinite}@keyframes p{50%{opacity:.3}}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}.card{background:linear-gradient(145deg,rgba(15,23,34,.96),rgba(7,11,17,.96));border:1px solid var(--line);border-radius:16px;padding:14px}.wide{grid-column:1/-1}.k{font-size:10px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);font-weight:900}.v{font-size:24px;font-weight:950;margin-top:5px}.small{font-size:11px;color:var(--muted);margin-top:5px;line-height:1.45}.cyan{color:var(--cyan)}.good{color:var(--green)}.bad{color:var(--red)}.amber{color:var(--amber)}
.row{display:flex;justify-content:space-between;gap:12px;padding:8px 0;border-bottom:1px solid rgba(255,255,255,.055);font-size:13px}.row:last-child{border:0}.row span:first-child{color:var(--muted)}.row b{text-align:right;overflow-wrap:anywhere}
.triplet{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:10px}.mini{background:#080d14;border:1px solid rgba(255,255,255,.05);border-radius:10px;padding:9px}.mini b{display:block;font-size:16px;margin-top:3px}
.headgrid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:10px}.head{background:#080d14;border:1px solid rgba(255,255,255,.055);border-radius:11px;padding:9px}.head .n{font-size:15px;font-weight:900;margin-top:3px}.head .m{font-size:10px;color:var(--muted);margin-top:3px}
.probrow{display:grid;grid-template-columns:68px 1fr 48px;gap:8px;align-items:center;margin-top:8px}.bar{height:7px;background:#08101a;border-radius:10px;overflow:hidden}.fill{height:100%;background:linear-gradient(90deg,var(--cyan),var(--green));border-radius:10px;transition:width .4s}.th{height:100%;border-right:2px solid var(--amber);opacity:.9}
.tag{display:inline-block;padding:4px 7px;border-radius:8px;background:#0b2831;color:var(--cyan);font-size:10px;font-weight:800;margin:2px}.rel{padding:6px 0;border-bottom:1px solid rgba(255,255,255,.04);font-size:11px}.rel:last-child{border:0}
.busgrid{display:grid;grid-template-columns:repeat(29,1fr);gap:3px;margin-top:11px}.bit{height:7px;border-radius:3px;background:#111a25;box-shadow:inset 0 0 0 1px rgba(255,255,255,.03)}.bit.seen{background:#17513a}.bit.target{background:#5a441a}.bit.meta{background:#273344}.bit.missing{background:#4b2028}
.off{display:inline-block;background:#2b1218;color:#ff8a96;border:1px solid #4d202a;border-radius:8px;padding:4px 7px;font-size:10px;font-weight:900;margin:2px}.footer{text-align:center;color:#52637a;font-size:10px;margin-top:16px}
@media(min-width:680px){.grid{grid-template-columns:repeat(4,1fr)}.card.wide{grid-column:span 2}.card.full{grid-column:1/-1}}
</style>
</head>
<body><div class="wrap">
<div class="hero"><div><div class="eyebrow">PANDORA · HYPE · LOCAL ONLY</div><div class="title">Local HIGH / LOW Engine</div><div class="sub" id="updated">Подключение…</div><div class="small">Quantum + Cortex · strict H1 teacher · 116-point live state</div></div><div class="pulse"><i class="dot"></i><span id="live">LIVE</span></div></div>

<div class="grid">
<div class="card"><div class="k">Статус</div><div class="v cyan" id="status">—</div><div class="small" id="fresh">—</div></div>
<div class="card"><div class="k">Следующий Local</div><div class="v amber" id="expected">—</div><div class="small">по последнему teacher pivot</div></div>
<div class="card"><div class="k">30D labels</div><div class="v" id="histlabels">—</div><div class="small">supervised pretrain</div></div>
<div class="card"><div class="k">Live labels</div><div class="v" id="livelabels">—</div><div class="small">pending <span id="pending">—</span></div></div>

<div class="card wide">
<div class="k">Текущий кандидат</div>
<div class="v" id="candidate">WAIT</div>
<div class="row"><span>Стадия</span><b id="stage">—</b></div>
<div class="row"><span>Возраст</span><b id="age">—</b></div>
<div class="row"><span>H1 prior</span><b id="h1prior">—</b></div>
<div class="row"><span>Источник кандидата</span><b id="source">—</b></div>
<div class="probrow"><span>60s</span><div class="bar"><div class="fill" id="p60bar"></div></div><b id="p60">—</b></div>
<div class="probrow"><span>180s</span><div class="bar"><div class="fill" id="p180bar"></div></div><b id="p180">—</b></div>
<div class="probrow"><span>300s</span><div class="bar"><div class="fill" id="p300bar"></div></div><b id="p300">—</b></div>
<div class="small">Порог каждой головы показан в таблице ниже. EARLY/PROBABLE ≠ подтверждённый teacher Local.</div>
</div>

<div class="card wide">
<div class="k">Teacher / structural anchor</div>
<div class="row"><span>Последний подтверждённый Local</span><b id="teacher">—</b></div>
<div class="row"><span>H1 shadow LOW</span><b id="h1low">—</b></div>
<div class="row"><span>H1 shadow HIGH</span><b id="h1high">—</b></div>
<div class="row"><span>H1 history labels LOW/HIGH</span><b id="h1labels">—</b></div>
<div class="small">K2 future используется только для созревшей teacher-метки; в predictive inputs не попадает.</div>
</div>

<div class="card wide">
<div class="k">Quantum · 6 Local heads</div>
<div class="headgrid" id="heads"></div>
<div class="small">LOW/HIGH × 60/180/300. Исторические true Local балансируются, чтобы модель не училась тривиальному «всегда false».</div>
</div>

<div class="card wide">
<div class="k">CORTEX · relationship analysis</div>
<div class="row"><span>Состояние</span><b id="cstate">—</b></div>
<div class="row"><span>Вердикт</span><b id="cverdict">—</b></div>
<div class="row"><span>Confidence</span><b id="cconf">—</b></div>
<div class="small"><b>Summary:</b> <span id="csummary">—</span></div>
<div class="small"><b>Поддерживает:</b> <span id="csupport">—</span></div>
<div class="small"><b>Против:</b> <span id="cagainst">—</span></div>
<div class="small"><b>Не хватает:</b> <span id="cmissing">—</span></div>
</div>

<div class="card wide">
<div class="k">Historical relationship match</div>
<div class="small good"><b>Совпадает с true Local:</b></div><div id="relsupport">—</div>
<div class="small bad"><b>Противоречит true Local:</b></div><div id="relagainst">—</div>
</div>

<div class="card wide">
<div class="k">116-point live data bus</div>
<div class="triplet"><div class="mini"><span class="k">Inputs seen</span><b id="seen">—</b></div><div class="mini"><span class="k">Contract</span><b>116</b></div><div class="mini"><span class="k">Mode</span><b>LIVE</b></div></div>
<div class="row"><span>Отсутствующие live inputs</span><b id="missingcount">—</b></div>
<div class="busgrid" id="bus"></div>
<div class="small">зелёный = causal input/quality получен · жёлтый = target/eval · серый = metadata · красный = input ещё не виделся</div>
</div>

<div class="card wide">
<div class="k">Последний model signal</div>
<div class="v amber" id="signal">—</div>
<div class="small" id="signalmeta">—</div>
</div>

<div class="card wide">
<div class="k">Архитектура</div>
<span class="tag">LOCAL MODEL ON</span><span class="tag">QUANTUM ON</span><span class="tag">CORTEX ON</span>
<span class="off">CATERPILLAR OFF</span><span class="off">FIBONACCI OFF</span><span class="off">DIRECT POLICY OFF</span><span class="off">ENTRY/EXIT/RE-ENTRY HEADS OFF</span>
<div class="small">Research-only. Реальные ордера отключены. Цель — только своевременное определение Local LOW / Local HIGH.</div>
</div>
</div>
<div class="footer">HYPE Local-Only · direct push + GitHub fallback · heartbeat 3s</div>
</div>
<script>
const $=id=>document.getElementById(id);
const pct=v=>v==null?"—":(Number(v)*100).toFixed(1)+"%";
const n=(v,d=2)=>v==null?"—":Number(v).toLocaleString("ru-RU",{maximumFractionDigits:d});
const bus=$("bus");for(let i=0;i<116;i++){const b=document.createElement("i");b.className="bit";b.title="Point "+(i+1);bus.appendChild(b)}
function setProb(id,v){$(id).textContent=pct(v);$(id+"bar").style.width=Math.max(0,Math.min(100,Number(v||0)*100))+"%"}
function relRows(rows){return (rows||[]).slice(0,8).map(r=>"<div class='rel'><b>"+r.feature+"</b> · effect "+n(r.effect,2)+" · now "+n(r.value,4)+" · hist "+n(r.historical_median,4)+"</div>").join("")||"—"}
function render(s){
 $("status").textContent=s.status||"—";
 const age=s.stream_age_seconds??s.freshness_seconds;
 $("fresh").textContent="fresh "+n(age,0)+"s · "+(s.transport||"—");
 $("expected").textContent=s.expected_side||"UNKNOWN";
 $("histlabels").textContent=n(s.historical_labels,0);
 $("livelabels").textContent=n(s.live_labels,0);$("pending").textContent=n(s.pending_labels,0);
 const c=s.candidate||{},p=c.probabilities||{};
 if(c.side){$("candidate").textContent=c.side+" @ "+n(c.extreme_price,4);$("candidate").className="v "+(c.side==="LOW"?"good":"bad")}
 else{$("candidate").textContent="WAIT";$("candidate").className="v amber"}
 $("stage").textContent=c.stage||"WATCH";$("age").textContent=c.age_s==null?"—":n(c.age_s,0)+"s";
 $("h1prior").textContent=pct(c.h1_prior);$("source").textContent=((c.evidence||{}).windows||[]).join(" / ")||((c.evidence||{}).proposal||"—");
 setProb("p60",p["60"]);setProb("p180",p["180"]);setProb("p300",p["300"]);
 const t=s.last_teacher_local||{};$("teacher").textContent=t.side?(t.side+" @ "+n(t.price,4)+" · hour "+new Date(t.hour_ms).toLocaleString("ru-RU")):"—";
 const h=s.h1_baseline||{},ht=s.h1_training||{};$("h1low").textContent=pct(h.low_probability);$("h1high").textContent=pct(h.high_probability);
 $("h1labels").textContent=n((ht.labels||{}).LOW,0)+" / "+n((ht.labels||{}).HIGH,0);
 const mr=s.model_report||{},labs=mr.labels||{},pos=mr.positive||{},ths=mr.thresholds||{};
 const keys=["LOW_60s","LOW_180s","LOW_300s","HIGH_60s","HIGH_180s","HIGH_300s"];
 $("heads").innerHTML=keys.map(k=>"<div class='head'><div class='k'>"+k+"</div><div class='n'>"+n(labs[k],0)+" labels</div><div class='m'>true "+n(pos[k],0)+" · threshold "+pct(ths[k])+"</div></div>").join("");
 const cx=s.cortex||{},cd=cx.decision||{};$("cstate").textContent=cx.state||s.cortex_state||"—";$("cverdict").textContent=cd.verdict||"—";$("cconf").textContent=pct(cd.confidence);
 $("csummary").textContent=cd.summary||"—";$("csupport").textContent=(cd.supporting_relationships||[]).join(" · ")||"—";$("cagainst").textContent=(cd.contradicting_relationships||[]).join(" · ")||"—";$("cmissing").textContent=(cd.missing_live_evidence||[]).join(" · ")||"—";
 const re=c.relationship_evidence||{};$("relsupport").innerHTML=relRows(re.supports);$("relagainst").innerHTML=relRows(re.contradicts);
 const fc=s.feature_contract||{},seen=new Set(fc.seen_input_ids||[]),targets=new Set(fc.target_eval_ids||[]),meta=new Set(fc.metadata_ids||[]);
 $("seen").textContent=n(fc.seen_input_count,0)+" / "+n((fc.supported_input_ids||[]).length,0);$("missingcount").textContent=n((fc.missing_seen_input_ids||[]).length,0);
 [...document.querySelectorAll(".bit")].forEach((b,i)=>{const id=i+1;b.className="bit "+(seen.has(id)?"seen":targets.has(id)?"target":meta.has(id)?"meta":"missing")});
 const sig=s.last_signal||{};$("signal").textContent=sig.side?(sig.state+" · "+sig.side+" @ "+n(sig.price,4)):"—";$("signalmeta").textContent=sig.side?("stage "+sig.stage+"s · p "+pct(sig.probability)+" · H1 "+pct(sig.h1_prior)):"нет сигнала";
 $("updated").textContent="данные "+new Date(s.updated_ts_ms||Date.now()).toLocaleTimeString("ru-RU")+" · "+(s.mode||"LOCAL_ONLY");
 $("live").textContent=(age!=null&&age<45)?"LIVE":(age!=null&&age<180?"STALE":"RECONNECT");
}
async function tick(){try{const r=await fetch("/api/status?x="+Date.now(),{cache:"no-store"});const j=await r.json();if(!r.ok)throw Error(j.error||("HTTP "+r.status));render(j)}catch(e){$("live").textContent="RECONNECT";$("updated").textContent=e.message}}
if(window.Telegram&&Telegram.WebApp){Telegram.WebApp.ready();Telegram.WebApp.expand();Telegram.WebApp.setHeaderColor("#05070b");Telegram.WebApp.setBackgroundColor("#05070b")}
tick();setInterval(tick,3000);
</script>
</body></html>'''

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
    try:
        dp=data.get("direct_policy") or {}
        last=dp.get("last_decision") or {}
        app.logger.info(
            "INGEST_ACCEPT run=%s sha=%s policy=%s action=%s direct_labels=%s",
            run_id,sha[:8],data.get("policy_contract_version"),
            last.get("action"),
            ((data.get("training_progress") or {}).get("heads") or {}).get("direct_policy",{}).get("labels"),
        )
    except Exception:
        pass
    return jsonify({"ok":True,"received_ts_ms":int(now*1000)})

@app.get("/healthz")
def health():
    now=time.time();age=None if not _cache["ingest_ts"] else max(0.0,now-_cache["ingest_ts"])
    return jsonify({"ok":True,"issue":ISSUE,"source":_cache["source"],"direct_age_seconds":age})
@app.get("/api/telegram/setup")
def setup():telegram_setup();return jsonify({"ok":True})

threading.Thread(target=lambda:(time.sleep(3),telegram_setup()),daemon=True).start()
