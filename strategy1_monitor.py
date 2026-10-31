"""Read-only Strategy 1 monitor. All numbers come from the actual PAPER ledger."""
import html
import json
from datetime import datetime, timezone


def render(data):
    def esc(v): return html.escape(str(v if v is not None else '—'),quote=True)
    def money(v):
        try:return f"{float(v):+,.2f}"
        except:return '—'
    def num(v):
        try:return f"{float(v):,.4f}"
        except:return '—'
    primary=data.get('strategy1_primary') or {}; engine=primary.get('engine') or {}; health=data.get('health') or {}
    details=engine.get('details') or {}; durable=primary.get('h1_durable') or {}; positions=primary.get('open_positions') or []
    symbols=list(data.get('local_experiment_symbols') or engine.get('symbols') or [])[:10]
    realized=float(primary.get('realized_pnl') or 0); unreal=float(primary.get('unrealized_pnl') or 0); total=realized+unreal
    equity=primary.get('total_equity'); started=primary.get('started_at') or primary.get('account_started_at') or '2026-10-29T07:36:30.730956+00:00'
    def table(head,rows):
        return '<div class="scroll"><table><tr>'+''.join('<th>'+esc(x)+'</th>' for x in head)+'</tr>'+(''.join('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in r)+'</tr>' for r in rows) or '<tr><td>Нет записей</td></tr>')+'</table></div>'
    piv=[]
    for sym in symbols:
        d=details.get(sym) or {}; a=d.get('h1_local') or durable.get(sym) or {}
        side='LONG' if a.get('entry_side')==1 else 'SHORT' if a.get('entry_side')==-1 else 'WAIT'
        piv.append([sym,a.get('pivot_type'),num(a.get('pivot_price')),side,a.get('confirmation_reason') or a.get('pivot_confirmation_policy') or '—'])
    op=[]
    for p in positions:
        f=p.get('features') or {}
        op.append([p.get('symbol'),'LONG' if p.get('side')==1 else 'SHORT',num(p.get('entry')),num(p.get('mark')),p.get('leverage'),num(p.get('margin_usd')),money(p.get('unrealized_pnl')),f.get('mfe_roe_pct'),f.get('mae_roe_pct')])
    histrows=[]
    for p in primary.get('closed_trades') or []:
        f=p.get('features') or {}
        histrows.append([p.get('closed'),p.get('symbol'),'LONG' if p.get('side')==1 else 'SHORT',num(p.get('entry')),num(p.get('exit')),money(p.get('pnl')),f.get('entry_kind'),p.get('reason'),f.get('mfe_roe_pct'),f.get('mae_roe_pct')])
    cards=[('START','$500.00'),('EQUITY','$'+num(equity)),('TOTAL PnL','$'+money(total)),('REALIZED','$'+money(realized)),('OPEN','$'+money(unreal)),('STARTED',started)]
    body='<header><div><b>PANDORA</b><span>STRATEGY 1 · PAPER</span></div><i>'+('LIVE ENGINE' if health.get('engine_active') else 'ENGINE WAIT')+'</i></header>'
    body+='<section class="cards">'+''.join('<article><small>'+esc(k)+'</small><strong>'+esc(v)+'</strong></article>' for k,v in cards)+'</section>'
    body+='<section><h2>H1 PIVOTS · 10 TOKENS</h2>'+table(['TOKEN','LOCAL','PIVOT PRICE','DIRECTION','CONFIRMATION'],piv)+'</section>'
    body+='<section><h2>OPEN POSITIONS</h2>'+table(['TOKEN','SIDE','ENTRY','MARK','LEV','MARGIN $','PnL $','MFE ROE %','MAE ROE %'],op)+'</section>'
    body+='<section><h2>TRADE HISTORY</h2><p><a href="/strategy1/history">FULL HISTORY →</a></p>'+table(['CLOSED','TOKEN','SIDE','ENTRY','EXIT','PnL $','ENTRY TYPE','EXIT','MFE %','MAE %'],histrows)+'</section>'
    css='''html{color-scheme:dark}*{box-sizing:border-box}body{margin:0;padding:18px;background:radial-gradient(circle at 12% 0,#10283e 0,transparent 34%),#04080d;color:#edf7ff;font:14px Inter,system-ui}body:before{content:"";position:fixed;inset:0;pointer-events:none;background-image:linear-gradient(rgba(54,220,255,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(54,220,255,.025) 1px,transparent 1px);background-size:30px 30px}main,#status{position:relative;max-width:1500px;margin:auto}header{display:flex;justify-content:space-between;align-items:center;padding:20px 22px;border:1px solid #1b516c;border-radius:18px;background:#07121dcc;box-shadow:0 0 35px #00c8ff12}header b{font-size:30px;letter-spacing:.18em}header span{margin-left:15px;color:#48dcff}header i{font-style:normal;color:#baff45;font:12px ui-monospace}section{margin-top:15px;padding:17px;border:1px solid #173d53;border-radius:16px;background:linear-gradient(145deg,#0b1a29f5,#07111df5)}.cards{display:grid;grid-template-columns:repeat(6,1fr);gap:11px;padding:0;border:0;background:none}.cards article{padding:16px;border:1px solid #20536e;border-radius:14px;background:#081622;min-height:95px}.cards article:nth-child(3){border-color:#9bd72c;box-shadow:0 0 24px #a7ef3014}.cards small{display:block;color:#789bb2;font-size:10px;letter-spacing:.12em}.cards strong{display:block;margin-top:13px;color:#f5fbff;font:700 21px ui-monospace}.cards article:nth-child(3) strong{color:#c8ff4c}h2{margin:0 0 12px;color:#68e3ff;font-size:15px;letter-spacing:.08em}.scroll{overflow:auto;border:1px solid #102f43;border-radius:11px}table{width:100%;border-collapse:collapse;min-width:850px}th,td{padding:11px;border-bottom:1px solid #112c3e;text-align:left;white-space:nowrap;font:11.5px ui-monospace}th{color:#54dfff;background:#0a1b29;position:sticky;top:0}a{color:#65e5ff}#status{text-align:right;color:#91d940;font:10px ui-monospace;margin-bottom:7px}@media(max-width:900px){.cards{grid-template-columns:repeat(2,1fr)}body{padding:8px}header{display:block}header i{display:block;margin-top:10px}}'''
    script='''<script>let busy=false;async function r(){if(busy||document.hidden)return;busy=true;try{let x=await fetch("/?r="+Date.now(),{cache:"no-store"});let d=new DOMParser().parseFromString(await x.text(),"text/html").getElementById("dash");document.getElementById("dash").replaceWith(document.importNode(d,true));document.getElementById("status").textContent="UPDATED "+new Date().toLocaleTimeString()}catch(e){document.getElementById("status").textContent="REFRESH ERROR"}finally{busy=false}}setInterval(r,5000)</script>'''
    return '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PANDORA</title><style>'+css+'</style><body><div id="status">PANDORA PAPER</div><main id="dash">'+body+'</main>'+script+'</body></html>'


def render_history(page):
    """Stable, paginated archive view; no balance or history mutation."""
    from urllib.parse import urlencode
    esc=lambda value:html.escape(str(value if value is not None else '—'),quote=True)
    rows=[]
    for trade in page.get('trades') or []:
        f=trade.get('features') or {}
        values=[trade.get('id'),trade.get('symbol'),trade.get('opened'),trade.get('closed'),trade.get('side'),
                trade.get('entry'),trade.get('exit'),trade.get('pnl'),f.get('entry_kind'),
                (f.get('candidate_selection') or {}).get('reason'),trade.get('reason')]
        rows.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in values)+'</tr>')
    args={'account':page['account']}
    if page.get('symbol'):args['symbol']=page['symbol']
    links='<a href="/">Монитор</a> · <a href="/strategy1/history?'+esc(urlencode(args))+'">Новейшие записи</a>'
    if page.get('next_before_id') is not None:
        links+=' · <a href="/strategy1/history?'+esc(urlencode({**args,'before':page['next_before_id']}))+'">Более ранние сделки →</a>'
    options=''.join('<option value="'+name+'"'+(' selected' if name==page['account'] else '')+'>'+name+'</option>'
                    for name in ('strategy1','legacy_s1','legacy_s2','legacy_s3','legacy_h1','legacy_shared'))
    form='<form><label>Журнал <select name="account">'+options+'</select></label> <label>Токен <input name="symbol" value="'+esc(page.get('symbol') or '')+'"></label> <button>Показать</button></form>'
    headings=('ID','Токен','Открыта','Закрыта','Сторона','Вход','Выход','PnL net fees','Тип входа','Причина входа','Причина выхода')
    return '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PANDORA · Архив</title><style>body{background:#090e18;color:#e2eaf7;font:14px system-ui;padding:20px}a{color:#9dc6ff}form{margin:20px 0}table{border-collapse:collapse}th,td{padding:12px;border-bottom:1px solid #25364b;text-align:left;white-space:nowrap}.scroll{overflow:auto}</style><h1>Полная сохранённая история · '+esc(page['account'])+'</h1><p>'+links+'</p>'+form+'<div class="scroll"><table><tr>'+''.join('<th>'+esc(v)+'</th>' for v in headings)+'</tr>'+(''.join(rows) or '<tr><td>Записей нет</td></tr>')+'</table></div><p>'+links+'</p></html>'
