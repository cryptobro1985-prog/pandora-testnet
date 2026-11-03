"""Codex Million PAPER-only Render entrypoint.

Active runtime contains only the frozen/patched Codex worker and a read-only
monitor. No PANDORA/Caterpillar executor is started here.
"""
from __future__ import annotations
import json,os,signal,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from codex_million_launcher import CODEX
from caterpillar_research_launcher import RESEARCH

STOP=threading.Event()

def esc(v):
    return str(v if v is not None else "—").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

HTML='''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Codex Million · PAPER</title><style>
:root{color-scheme:dark;font-family:system-ui;background:#070b16;color:#edf4ff}body{margin:0}.wrap{max-width:1500px;margin:auto;padding:24px}
h1{font-size:38px;margin:0 0 4px}.sub{color:#9aabc8;font-size:13px;line-height:1.45}.top,.grid{display:grid;gap:10px}.top{grid-template-columns:repeat(5,1fr);margin:16px 0;position:sticky;top:0;z-index:5;background:#070b16;padding:8px 0}.tile,.card{border:1px solid #31405f;background:#10182a;border-radius:14px;padding:13px;min-width:0}.tile b{display:block;font-size:20px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.tile small{color:#9aabc8}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.card h2{margin:0 0 10px;color:#6cddff;font-size:20px;display:flex;justify-content:space-between;gap:8px}.m{display:grid;grid-template-columns:minmax(92px,.8fr) minmax(0,1.2fr);gap:7px 10px;font:12px ui-monospace,monospace}.m span{min-width:0;overflow-wrap:anywhere}.m span:nth-child(odd){color:#9aabc8}.short{color:#ff829c;font-size:12px}.ok{color:#7ef5bb}.warn{color:#fff17b}.history{margin-top:18px;overflow:hidden}.tablewrap{overflow-x:auto;-webkit-overflow-scrolling:touch}table{width:100%;border-collapse:collapse;font-size:11px;min-width:620px}td,th{padding:7px;border-bottom:1px solid #26334d;text-align:left;white-space:nowrap}.research{margin:10px 0 14px;padding:10px 12px;border:1px solid #31405f;border-radius:12px;background:#0d1424;font-size:12px;color:#9aabc8}
@media(max-width:600px){.wrap{padding:12px 10px 28px}h1{font-size:27px}.sub{font-size:11px}.top{grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin:10px 0}.tile{padding:9px 8px;border-radius:10px}.tile b{font-size:15px}.tile small{font-size:9px}.grid{grid-template-columns:1fr;gap:9px}.card{padding:11px}.card h2{font-size:18px}.m{font-size:11px;grid-template-columns:96px minmax(0,1fr);gap:6px 8px}.history h2{font-size:18px}}</style></head>
<body><div class="wrap"><h1>Codex Million · SHORT10</h1><div class="sub">PAPER ONLY · 10% margin/token · 30x · flow 30/180/300 · MFE protection · fixed 10 tokens</div>
<div id="top" class="top"></div><div id="research" class="research">6H Research: starting…</div><div id="grid" class="grid"></div><div class="history"><h2>Closed trades</h2><div id="history" class="tablewrap"></div></div></div>
<script>
const f=(x,d=2)=>x==null?'—':Number(x).toFixed(d), money=x=>x==null?'—':'$'+f(x,2);
function local(t){let a=t.local_state||t.current_local||t.confirmed_local||{};let c=a.confirmed_local||a;return (c.pivot_type||c.type||a.pivot_type||'—')+' '+(c.pivot_price??a.pivot_price??'—')}
function row(k,v){return '<span>'+k+'</span><span>'+String(v??'—')+'</span>'}
async function tick(){try{let [r,rr]=await Promise.all([fetch('/api/codex',{cache:'no-store'}),fetch('/api/research',{cache:'no-store'})]),d=await r.json(),rd=await rr.json();
document.getElementById('research').innerHTML='6H Research: <b class="'+(rd.online?'ok':'warn')+'">'+String(rd.status||'—')+'</b> · '+(rd.online?'LIVE':'not running')+' · fixed 10 tokens · historical 30D runs separately';
let acc=d.account||{};document.getElementById('top').innerHTML=[
['STATUS',d.status],['EQUITY',money(d.equity)],['REALIZED',money(d.realized_pnl)],['UNREALIZED',money(d.unrealized_pnl)],['OPEN',String((d.positions||[]).length)]
].map(x=>'<div class="tile"><small>'+x[0]+'</small><b>'+x[1]+'</b></div>').join('');
let pos={};for(let p of d.positions||[])pos[p.symbol]=p;
document.getElementById('grid').innerHTML=(d.tokens||[]).map(t=>{let p=pos[t.symbol]||{},ft=p.features||{},flow=t.flow_context||t.flow_state||{},dir=t.direction??t.entry_side??(t.local_state||{}).entry_side;
return '<div class="card"><h2>'+t.symbol+' <span class="short">SHORT ONLY</span></h2><div class="m">'+
row('Local H1',local(t))+row('Structure',t.structure_state||t.structure||t.state)+row('Direction',dir==-1?'SHORT':dir==1?'LONG':'—')+
row('Price',t.price??t.last)+row('BUY',f(t.buy_volume??flow.buy_notional,0))+row('SELL',f(t.sell_volume??flow.sell_notional,0))+
row('30s',JSON.stringify((flow.windows||{})['30']||{}))+row('180s',JSON.stringify((flow.windows||{})['180']||{}))+row('300s',JSON.stringify((flow.windows||{})['300']||{}))+
row('Position',p.side==-1?'SHORT':p.side==1?'LONG':'—')+row('Entry',p.entry??p.entry_price)+row('Margin',money(p.margin??p.margin_usd))+row('Leverage',(p.leverage??'—')+'x')+
row('PnL',money(p.unrealized_pnl??p.pnl_usdt))+row('Peak MFE',money(ft.peak_mfe_usd??ft.mfe_usd))+row('MAE',money(ft.mae_usd))+row('MFE giveback',money(ft.mfe_giveback_usd))+
'</div></div>'}).join('');
let tr=(d.trades||[]).slice(0,100);document.getElementById('history').innerHTML='<table><tr><th>Symbol</th><th>Side</th><th>PnL</th><th>MFE</th><th>Reason</th><th>Closed</th></tr>'+tr.map(x=>{let ft=x.features||{};return '<tr><td>'+x.symbol+'</td><td>'+ (x.side==-1?'SHORT':'LONG')+'</td><td>'+money(x.pnl)+'</td><td>'+money(ft.peak_mfe_usd??ft.mfe_usd)+'</td><td>'+String(x.reason||'—')+'</td><td>'+String(x.closed||'—')+'</td></tr>'}).join('')+'</table>';
}catch(e){document.getElementById('top').innerHTML='<div class="tile warn">WAITING: '+e+'</div>'}}
tick();setInterval(tick,1000);
</script></body></html>'''

class H(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def sendj(self,obj,code=200):
        b=json.dumps(obj,default=str).encode();self.send_response(code);self.send_header("Content-Type","application/json");self.send_header("Cache-Control","no-store");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b)
    def do_GET(self):
        if self.path.startswith("/api/codex"): return self.sendj(CODEX.snapshot())
        if self.path.startswith("/api/research"): return self.sendj(RESEARCH.snapshot())
        if self.path.startswith("/health"): return self.sendj({"ok":True,"codex":CODEX.snapshot().get("status"),"research":RESEARCH.snapshot().get("status")})
        b=HTML.encode();self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8");self.send_header("Cache-Control","no-store");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b)

def main():
    for sig in (signal.SIGTERM,signal.SIGINT):
        signal.signal(sig,lambda *_:STOP.set())
    t=threading.Thread(target=CODEX.run,args=(STOP,),daemon=True,name="codex_million");t.start()
    rt=threading.Thread(target=RESEARCH.run,args=(STOP,),daemon=True,name="caterpillar_research_6h");rt.start()
    port=int(os.getenv("PORT","10000"));server=ThreadingHTTPServer(("0.0.0.0",port),H);server.timeout=1
    print("[CODEX_ONLY] PAPER_ONLY port=%s"%port,flush=True)
    try:
        while not STOP.is_set():server.handle_request()
    finally:
        STOP.set();server.server_close();t.join(timeout=8);rt.join(timeout=8)

if __name__=="__main__":main()
