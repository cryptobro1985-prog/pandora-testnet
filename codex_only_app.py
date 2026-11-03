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

HTML=r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Codex Million PAPER</title><style>
:root{color-scheme:dark;font-family:system-ui;background:#070b16;color:#edf4ff}body{margin:0}.wrap{max-width:1200px;margin:auto;padding:12px}
h1{font-size:28px;margin:0}.sub{color:#9aabc8;font-size:11px}.top,.grid{display:grid;gap:8px}.top{grid-template-columns:repeat(3,minmax(0,1fr));margin:12px 0}.tile,.card,.research{border:1px solid #31405f;background:#10182a;border-radius:12px;padding:10px;min-width:0}.tile b{display:block;font-size:15px}.tile small{font-size:9px;color:#9aabc8}.grid{grid-template-columns:repeat(2,minmax(0,1fr));margin-top:10px}.card h2{margin:0 0 8px;color:#6cddff;font-size:18px}.m{display:grid;grid-template-columns:96px minmax(0,1fr);gap:6px 8px;font:11px ui-monospace,monospace}.m span:nth-child(odd){color:#9aabc8}.m span{overflow-wrap:anywhere}.ok{color:#7ef5bb}.warn{color:#fff17b}.history{margin-top:14px;overflow-x:auto}table{min-width:620px;width:100%;border-collapse:collapse;font-size:11px}td,th{padding:7px;border-bottom:1px solid #26334d;white-space:nowrap;text-align:left}
@media(max-width:600px){.wrap{padding:10px}.grid{grid-template-columns:1fr}.top{position:sticky;top:0;background:#070b16;z-index:5}.card{padding:10px}}
</style></head><body><div class="wrap"><h1>Codex Million · PAPER</h1><div class="sub">fixed 10 · H1 locals · executed flow · 30/180/300 · MFE/MAE</div>
<div id="top" class="top"></div><div id="research" class="research">Research…</div><div id="grid" class="grid"></div><div class="history"><h2>Closed trades</h2><div id="history"></div></div></div>
<script>
const FIXED=['ZEC','HYPE','NEAR','SOL','ENA','1000PEPE','DOGE','SUI','AAVE','WLD'];
const num=(x,d=2)=>x==null?'—':Number(x).toFixed(d), money=x=>x==null?'—':'$'+num(x,2);
const row=(k,v)=>'<span>'+k+'</span><span>'+String(v??'—')+'</span>';
function loc(t){let a=t.local_state||t.confirmed_local||{},q=a.confirmed_local||a;return (q.pivot_type||q.kind||q.type||'—')+' '+(q.pivot_price??q.price??'—')}
async function tick(){try{
 const [r,rr]=await Promise.all([fetch('/api/codex',{cache:'no-store'}),fetch('/api/research',{cache:'no-store'})]);
 const d=await r.json(), rd=await rr.json(), tokens=d.tokens||[], positions=d.positions||[], diag=d.entry_diagnostics||{}, ready=(d.health||{}).token_readiness||{};
 document.getElementById('top').innerHTML=[['STATUS',d.status||'—'],['EQUITY',money(d.equity)],['TOKENS',tokens.length+'/10'],['OPEN',positions.length],['CLOSED',(d.trades||[]).length],['RISK',d.risk_ready===true?'READY':'WARMING']].map(x=>'<div class="tile"><small>'+x[0]+'</small><b>'+x[1]+'</b></div>').join('');
 document.getElementById('research').innerHTML='6H Research: <b class="'+(rd.online?'ok':'warn')+'">'+(rd.status||'—')+'</b>';
 let by=Object.fromEntries(tokens.map(x=>[x.symbol,x])), pos=Object.fromEntries(positions.map(x=>[x.symbol,x]));
 document.getElementById('grid').innerHTML=FIXED.map(s=>{let t=by[s]||{symbol:s},p=pos[s]||{},f=p.features||{},fl=t.flow_context||t.flow_state||{},h=ready[s]||{},g=diag[s]||{},dir=t.direction??t.entry_side??(t.local_state||{}).entry_side;
 return '<div class="card"><h2>'+s+'</h2><div class="m">'+row('Local H1',loc(t))+row('Structure',t.structure_state||t.structure||t.state||'WAITING_DATA')+row('Direction',dir==-1?'SHORT':dir==1?'LONG':'—')+row('H1 ready',h.h1?'YES':'NO')+row('Flow ready',h.executed_flow?'YES':'NO')+row('Evidence',h.evidence_ready?'YES':'NO')+row('Entry state',g.reason||g.status||t.action_reason||'WAITING')+row('Price',t.price??t.last)+row('BUY',num(t.buy_volume??fl.buy_notional,0))+row('SELL',num(t.sell_volume??fl.sell_notional,0))+row('Position',p.side==-1||p.side==='SHORT'?'SHORT':p.side==1||p.side==='LONG'?'LONG':'—')+row('Entry',p.entry??p.entry_price)+row('Margin',money(p.margin??p.margin_usd))+row('Leverage',(p.leverage??'—')+'x')+row('PnL',money(p.unrealized_pnl??p.pnl_usdt))+row('MFE',money(f.peak_mfe_usd??f.mfe_usd))+row('MAE',money(f.mae_usd))+'</div></div>'}).join('');
 let tr=(d.trades||[]).slice(0,100);document.getElementById('history').innerHTML='<table><tr><th>Symbol</th><th>Side</th><th>PnL</th><th>Reason</th><th>Closed</th></tr>'+tr.map(x=>'<tr><td>'+x.symbol+'</td><td>'+(x.side==-1?'SHORT':'LONG')+'</td><td>'+money(x.pnl)+'</td><td>'+String(x.reason||'—')+'</td><td>'+String(x.closed||'—')+'</td></tr>').join('')+'</table>';
}catch(e){document.getElementById('research').textContent='MONITOR ERROR: '+e}}
tick();setInterval(tick,1500);
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
