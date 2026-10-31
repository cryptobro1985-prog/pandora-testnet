"""Read-only PANDORA Strategy 1 PAPER monitor."""
import html
from urllib.parse import urlencode

def _e(v): return html.escape(str("—" if v is None else v), quote=True)
def _n(v, digits=4):
    try: return f"{float(v):,.{digits}f}"
    except: return "—"
def _m(v):
    try: return f"$ {float(v):+,.2f}"
    except: return "—"
def _table(head, rows):
    body="".join("<tr>"+"".join("<td>"+_e(x)+"</td>" for x in r)+"</tr>" for r in rows)
    if not body: body='<tr><td colspan="'+str(len(head))+'">Нет записей</td></tr>'
    return '<div class="scroll"><table><tr>'+"".join("<th>"+_e(x)+"</th>" for x in head)+"</tr>"+body+"</table></div>"

def render(data):
    primary=data.get("strategy1_primary") or {}
    engine=primary.get("engine") or {}
    health=data.get("health") or {}
    details=engine.get("details") or {}
    durable=primary.get("h1_durable") or {}
    symbols=list(data.get("local_experiment_symbols") or engine.get("symbols") or [])[:12]
    positions=primary.get("open_positions") or []
    realized=float(primary.get("realized_pnl") or 0)
    unreal=float(primary.get("unrealized_pnl") or 0)
    equity=primary.get("total_equity")
    started=primary.get("started_at") or primary.get("account_started_at") or "—"
    piv=[]
    for sym in symbols:
        d=details.get(sym) or {}
        a=d.get("h1_local") or durable.get(sym) or {}
        side="LONG" if a.get("entry_side")==1 else "SHORT" if a.get("entry_side")==-1 else "WAIT"
        piv.append([sym,a.get("pivot_type"),_n(a.get("pivot_price")),side,a.get("pending_pivot_type") or "—",a.get("policy") or a.get("pivot_confirmation_policy") or "—"])
    op=[]
    for p in positions:
        f=p.get("features") or {}
        op.append([p.get("symbol"),"LONG" if p.get("side")==1 else "SHORT",_n(p.get("entry")),_n(p.get("mark")),p.get("leverage"),_m(p.get("margin_usd") or p.get("margin")),_m(p.get("unrealized_pnl")),_n(f.get("mfe_roe_pct"),2),_n(f.get("mae_roe_pct"),2)])
    hist=[]
    for p in primary.get("closed_trades") or []:
        f=p.get("features") or {}
        hist.append([p.get("closed"),p.get("symbol"),"LONG" if p.get("side")==1 else "SHORT",_n(p.get("entry")),_n(p.get("exit")),_m(p.get("pnl")),f.get("entry_kind") or "—",p.get("reason") or "—",_n(f.get("mfe_roe_pct"),2),_n(f.get("mae_roe_pct"),2)])
    cards=[("START","$500.00"),("EQUITY",_m(equity)),("TOTAL PnL",_m(realized+unreal)),("REALIZED",_m(realized)),("OPEN",_m(unreal)),("STARTED",started)]
    body='<header><div><b>PANDORA</b><span>STRATEGY 1 · PAPER</span></div><i>'+("LIVE ENGINE" if health.get("engine_active") else "ENGINE WAIT")+"</i></header>"
    body+='<section class="cards">'+"".join("<article><small>"+_e(k)+"</small><strong>"+_e(v)+"</strong></article>" for k,v in cards)+"</section>"
    body+='<section><h2>H1 PIVOTS · '+str(len(symbols))+' TOKENS</h2>'+_table(["TOKEN","LOCAL","PIVOT","DIRECTION","PENDING","POLICY"],piv)+"</section>"
    body+='<section><h2>OPEN POSITIONS</h2>'+_table(["TOKEN","SIDE","ENTRY","MARK","LEV","MARGIN","PnL","MFE %","MAE %"],op)+"</section>"
    body+='<section><h2>TRADE HISTORY</h2><p><a href="/strategy1/history">FULL HISTORY →</a></p>'+_table(["CLOSED","TOKEN","SIDE","ENTRY","EXIT","PnL $","ENTRY TYPE","EXIT","MFE %","MAE %"],hist)+"</section>"
    css="""html{color-scheme:dark}*{box-sizing:border-box}body{margin:0;padding:16px;background:#04080d;color:#edf7ff;font:14px system-ui}main,#status{max-width:1500px;margin:auto}header{display:flex;justify-content:space-between;align-items:center;padding:20px;border:1px solid #1b516c;border-radius:16px;background:#07121d}header b{font-size:28px;letter-spacing:.16em}header span{margin-left:12px;color:#48dcff}header i{color:#baff45;font-style:normal}.cards{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;padding:0;border:0;background:none}.cards article{padding:15px;border:1px solid #20536e;border-radius:12px;background:#081622}.cards small{display:block;color:#789bb2}.cards strong{display:block;margin-top:10px;font:700 19px ui-monospace}section{margin-top:14px;padding:15px;border:1px solid #173d53;border-radius:14px;background:#08131f}h2{color:#68e3ff;font-size:14px}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;min-width:850px}th,td{padding:10px;border-bottom:1px solid #112c3e;text-align:left;white-space:nowrap;font:11px ui-monospace}th{color:#54dfff}a{color:#65e5ff}#status{text-align:right;color:#91d940;font:10px ui-monospace;margin-bottom:6px}@media(max-width:900px){.cards{grid-template-columns:repeat(2,1fr)}body{padding:7px}header{display:block}header i{display:block;margin-top:8px}}"""
    script="""<script>let b=false;async function r(){if(b||document.hidden)return;b=true;try{const x=await fetch('/?r='+Date.now(),{cache:'no-store'});if(!x.ok)throw Error(x.status);const t=await x.text();const d=new DOMParser().parseFromString(t,'text/html').getElementById('dash');if(!d)throw Error('dash');document.getElementById('dash').replaceWith(document.importNode(d,true));document.getElementById('status').textContent='UPDATED '+new Date().toLocaleTimeString()}catch(e){document.getElementById('status').textContent='REFRESH ERROR'}finally{b=false}}setInterval(r,5000)</script>"""
    return '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PANDORA LIVE</title><style>'+css+'</style><body><div id="status">PANDORA PAPER</div><main id="dash">'+body+"</main>"+script+"</body></html>"

def render_history(page):
    rows=[]
    for t in page.get("trades") or []:
        f=t.get("features") or {}
        rows.append([t.get("id"),t.get("symbol"),t.get("opened"),t.get("closed"),t.get("side"),t.get("entry"),t.get("exit"),_m(t.get("pnl")),f.get("entry_kind") or "—",(f.get("candidate_selection") or {}).get("reason") or "—",t.get("reason") or "—"])
    args={"account":page.get("account") or "strategy1"}
    if page.get("symbol"): args["symbol"]=page["symbol"]
    links='<a href="/">Монитор</a> · <a href="/strategy1/history?'+_e(urlencode(args))+'">Новейшие</a>'
    if page.get("next_before_id") is not None:
        links+=' · <a href="/strategy1/history?'+_e(urlencode({**args,"before":page["next_before_id"]}))+'">Ранее →</a>'
    table=_table(["ID","TOKEN","OPEN","CLOSED","SIDE","ENTRY","EXIT","PnL","ENTRY TYPE","ENTRY REASON","EXIT REASON"],rows)
    return '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PANDORA HISTORY</title><style>body{background:#090e18;color:#e2eaf7;font:14px system-ui;padding:18px}a{color:#9dc6ff}.scroll{overflow:auto}table{border-collapse:collapse}th,td{padding:10px;border-bottom:1px solid #25364b;white-space:nowrap}</style><h1>PANDORA · HISTORY</h1><p>'+links+"</p>"+table+"<p>"+links+"</p></html>"
