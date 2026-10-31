"""Read-only PANDORA Strategy 1.1 / 1.2 A/B PAPER monitor."""
import html
from urllib.parse import urlencode

def _e(v): return html.escape(str("—" if v is None else v), quote=True)
def _n(v,digits=4):
    try:return f"{float(v):,.{digits}f}"
    except:return "—"
def _m(v):
    try:return f"$ {float(v):+,.2f}"
    except:return "—"
def _side(v):
    if v in (1,"1","LONG","long"):return "LONG"
    if v in (-1,"-1","SHORT","short"):return "SHORT"
    return "WAIT"
def _table(head,rows):
    body="".join("<tr>"+"".join("<td>"+_e(x)+"</td>" for x in r)+"</tr>" for r in rows)
    if not body:body='<tr><td colspan="'+str(len(head))+'">Нет записей</td></tr>'
    return '<div class="scroll"><table><tr>'+"".join("<th>"+_e(x)+"</th>" for x in head)+"</tr>"+body+"</table></div>"

def _cards(primary):
    realized=float(primary.get("realized_pnl") or 0)
    unreal=float(primary.get("unrealized_pnl") or 0)
    return [
      ("START","$500.00"),
      ("EQUITY",_m(primary.get("total_equity"))),
      ("TOTAL PnL",_m(realized+unreal)),
      ("REALIZED",_m(realized)),
      ("OPEN",_m(unreal)),
      ("STARTED",primary.get("started_at") or primary.get("account_started_at") or "—"),
    ]

def _positions(primary):
    rows=[]
    for p in primary.get("open_positions") or []:
        f=p.get("features") or {}
        rows.append([p.get("symbol"),_side(p.get("side")),_n(p.get("entry")),_n(p.get("mark")),
          p.get("leverage"),_m(p.get("margin_usd") or p.get("margin")),_m(p.get("unrealized_pnl")),
          _n(f.get("mfe_roe_pct"),2),_n(f.get("mae_roe_pct"),2)])
    return rows

def _history(primary):
    rows=[]
    for p in primary.get("closed_trades") or []:
        f=p.get("features") or {}
        rows.append([p.get("closed"),p.get("symbol"),_side(p.get("side")),_n(p.get("entry")),_n(p.get("exit")),
          _m(p.get("pnl")),f.get("entry_kind") or "—",p.get("reason") or "—",
          _n(f.get("mfe_roe_pct"),2),_n(f.get("mae_roe_pct"),2)])
    return rows

def _pivot_rows(symbols,source,details=None):
    rows=[];details=details or {}
    for sym in symbols:
        a=(details.get(sym) or {}).get("h1_local") or source.get(sym) or {}
        rows.append([sym,a.get("pivot_type"),_n(a.get("pivot_price")),_side(a.get("entry_side")),
          a.get("pending_pivot_type") or "—",a.get("policy") or a.get("pivot_confirmation_policy") or "—"])
    return rows

def render(data):
    cur=data.get("strategy1_primary") or {}
    legacy=data.get("strategy11_legacy") or {}
    s13=data.get("strategy13") or {}
    s14=data.get("strategy14") or {}
    health=data.get("health") or {}
    symbols=list(data.get("local_experiment_symbols") or [])
    cur_engine=cur.get("engine") or {}
    cur_details=cur_engine.get("details") or {}
    cur_h1=cur.get("h1_durable") or {}
    legacy_h1=legacy.get("h1") or {}
    discovery=data.get("discovery") or {}

    selected={x.get("symbol"):x for x in discovery.get("selected") or []}
    disc_rows=[]
    for sym in discovery.get("selected_symbols") or []:
        x=selected.get(sym) or {}
        ch=x.get("change_24h_pct")
        move="PUMP" if isinstance(ch,(int,float)) and ch>0 else "DUMP" if isinstance(ch,(int,float)) and ch<0 else "FLAT"
        disc_rows.append([sym,move,_n(ch,2),_n(x.get("range_24h_pct"),2),_m(x.get("turnover_24h")),x.get("last")])

    def panel(title,subtitle,primary,pivots):
        cards='<div class="cards">'+"".join("<article><small>"+_e(k)+"</small><strong>"+_e(v)+"</strong></article>" for k,v in _cards(primary))+"</div>"
        return '<section class="strategy"><h2>'+_e(title)+'</h2><p class="sub">'+_e(subtitle)+'</p>'+cards+          '<h3>H1 LOCALS</h3>'+_table(["TOKEN","LOCAL","PIVOT","DIRECTION","PENDING","POLICY"],pivots)+          '<h3>OPEN POSITIONS</h3>'+_table(["TOKEN","SIDE","ENTRY","MARK","LEV","MARGIN","PnL","MFE %","MAE %"],_positions(primary))+          '<h3>TRADE HISTORY</h3>'+_table(["CLOSED","TOKEN","SIDE","ENTRY","EXIT","PnL $","ENTRY TYPE","EXIT","MFE %","MAE %"],_history(primary))+'</section>'

    body='<header><div><b>PANDORA</b><span>STRATEGY 1 · LIVE A/B PAPER</span></div><i>'+("LIVE ENGINE" if health.get("engine_active") else "ENGINE WAIT")+"</i></header>"
    body+='<section><h2>BYBIT VOLATILITY DISCOVERY</h2><p class="sub">Top selected USDT-linear movers by absolute 24h change. Same candidate pool is fed to both 1.1 and 1.2; actual entries still follow each strategy.</p>'+_table(["TOKEN","MOVE","24H %","24H RANGE %","TURNOVER","LAST"],disc_rows)+'</section>'
    body+='<div class="abgrid">'
    body+=panel("STRATEGY 1.1 · LEGACY CATERPILLAR","Historical M1/M3/M5 executed-flow + MFE implementation · independent $500 PAPER ledger",legacy,_pivot_rows(symbols,legacy_h1))
    body+=panel("STRATEGY 1.2 · CURRENT CATERPILLAR","Current executed-flow Caterpillar · independent $500 PAPER ledger",cur,_pivot_rows(symbols,cur_h1,cur_details))
    body+=panel("STRATEGY 1.3 · PURE H1 SWING","Confirmed H1 Local Low → LONG until Local High; Local High → SHORT until Local Low · no intrswing exits",s13,_pivot_rows(s13.get("symbols") or [],{}))
    body+=panel("STRATEGY 1.4 · HISTORICAL 848b3c6","Historical Caterpillar comparison from audited 848b3c6 mechanics · independent $500 PAPER ledger",s14,_pivot_rows(symbols,{}))
    body+='</div>'

    css="""html{color-scheme:dark}*{box-sizing:border-box}body{margin:0;padding:14px;background:#03070c;color:#edf7ff;font:14px system-ui}main,#status{max-width:1800px;margin:auto}header{display:flex;justify-content:space-between;align-items:center;padding:20px;border:1px solid #1b516c;border-radius:16px;background:#07121d}header b{font-size:28px;letter-spacing:.16em}header span{margin-left:12px;color:#48dcff}header i{color:#baff45;font-style:normal}.abgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.strategy{min-width:0}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:14px}.cards article{padding:12px;border:1px solid #20536e;border-radius:12px;background:#081622}.cards small{display:block;color:#789bb2}.cards strong{display:block;margin-top:8px;font:700 17px ui-monospace}section{margin-top:12px;padding:14px;border:1px solid #173d53;border-radius:14px;background:#08131f}h2{color:#68e3ff;font-size:15px}h3{color:#9bdfff;font-size:12px;margin-top:17px}.sub{color:#85a6b9;font-size:12px}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;min-width:760px}th,td{padding:8px;border-bottom:1px solid #112c3e;text-align:left;white-space:nowrap;font:10px ui-monospace}th{color:#54dfff}#status{text-align:right;color:#91d940;font:10px ui-monospace;margin-bottom:6px}@media(max-width:1100px){.abgrid{grid-template-columns:1fr}.cards{grid-template-columns:repeat(2,1fr)}body{padding:7px}header{display:block}header i{display:block;margin-top:8px}}"""
    script="""<script>let b=false;async function r(){if(b||document.hidden)return;b=true;try{const x=await fetch('/?r='+Date.now(),{cache:'no-store'});if(!x.ok)throw Error(x.status);const t=await x.text();const d=new DOMParser().parseFromString(t,'text/html').getElementById('dash');if(!d)throw Error('dash');document.getElementById('dash').replaceWith(document.importNode(d,true));document.getElementById('status').textContent='UPDATED '+new Date().toLocaleTimeString()}catch(e){document.getElementById('status').textContent='REFRESH ERROR'}finally{b=false}}setInterval(r,5000)</script>"""
    return '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PANDORA A/B</title><style>'+css+'</style><body><div id="status">PANDORA PAPER</div><main id="dash">'+body+"</main>"+script+"</body></html>"

def render_history(page):
    rows=[]
    for t in page.get("trades") or []:
        f=t.get("features") or {}
        rows.append([t.get("id"),t.get("symbol"),t.get("opened"),t.get("closed"),_side(t.get("side")),t.get("entry"),t.get("exit"),_m(t.get("pnl")),f.get("entry_kind") or "—",(f.get("candidate_selection") or {}).get("reason") or "—",t.get("reason") or "—"])
    args={"account":page.get("account") or "strategy1"}
    if page.get("symbol"):args["symbol"]=page["symbol"]
    links='<a href="/">Монитор</a> · <a href="/strategy1/history?'+_e(urlencode(args))+'">Новейшие</a>'
    if page.get("next_before_id") is not None:links+=' · <a href="/strategy1/history?'+_e(urlencode({**args,"before":page["next_before_id"]}))+'">Ранее →</a>'
    table=_table(["ID","TOKEN","OPEN","CLOSED","SIDE","ENTRY","EXIT","PnL","ENTRY TYPE","ENTRY REASON","EXIT REASON"],rows)
    return '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PANDORA HISTORY</title><style>body{background:#090e18;color:#e2eaf7;font:14px system-ui;padding:18px}a{color:#9dc6ff}.scroll{overflow:auto}table{border-collapse:collapse}th,td{padding:10px;border-bottom:1px solid #25364b;white-space:nowrap}</style><h1>PANDORA · HISTORY</h1><p>'+links+"</p>"+table+"<p>"+links+"</p></html>"
