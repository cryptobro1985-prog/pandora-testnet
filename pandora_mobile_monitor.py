"""Compact read-only PAPER dashboard for narrow Samsung screens."""
import html
from datetime import datetime, timezone
from pandora_monitor import _summary, _tokens, _finite, _price, _side

def e(v): return html.escape(str("—" if v is None else v),quote=True)
def money(v):
    x=_finite(v)
    return "—" if x is None else f"{x:+,.2f} $"
def number(v):
    x=_finite(v)
    return "—" if x is None else f"{x:,.2f}"
def pct(v):
    x=_finite(v)
    return "—" if x is None else f"{x:+,.2f}%"
def local(t):
    state=t.get("local_state") or {}
    confirmed=t.get("confirmed_local") or state.get("confirmed_local") or {}
    execution=t.get("execution_local") or state.get("execution_local") or {}
    forming=t.get("forming_local") or state.get("forming_local") or {}
    if not isinstance(confirmed,dict): confirmed={}
    if not isinstance(execution,dict): execution={}
    if not isinstance(forming,dict): forming={}
    active=execution if execution.get("pivot_type") and execution.get("pivot_price") is not None else confirmed
    valid=bool(active.get("pivot_type") and active.get("pivot_price") is not None)
    blocked=bool(t.get("entry_blocked",state.get("entry_blocked",False)))
    live=state.get("live_structure_fresh",True) is not False
    raw_side=t.get("direction") or t.get("entry_side") or active.get("entry_side")
    direction=_side(raw_side) if valid and live and not blocked else "WAIT"
    forming_text=(str(forming.get("pivot_type"))+" · "+_price(forming.get("pivot_price"))) if forming.get("pivot_type") else "—"
    return (str(active.get("pivot_type") or "WAIT"),_price(active.get("pivot_price")),
            direction,forming_text,("НЕ ПОДТВЕРЖДЕНО" if not valid else
            "BLOCKED" if blocked else "STALE" if not live else "CONFIRMED"))
def render(data):
    p=data.get("pandora") or {}
    start,equity,total,total_pct=_summary(p)
    now=datetime.now(timezone.utc)
    started=p.get("started_at") or p.get("start_time") or data.get("started_at")
    uptime="—"
    try:
        if started:
            sec=max(0,int((now-datetime.fromisoformat(str(started).replace("Z","+00:00"))).total_seconds()))
            uptime=f"{sec//3600} ч {(sec%3600)//60} мин"
    except (ValueError,TypeError): pass
    sections=[]
    for t in _tokens(data)[:5]:
        name=t.get("symbol")
        typ,level,direction,forming,structure_status=local(t)
        pos=t.get("position") or {}
        state=_side(pos.get("side")) if pos else "НЕТ"
        sections.append(f'<article><div class="heading"><b>{e(name)}</b><strong class="{e(direction.lower())}">{e(direction)}</strong></div><div class="kv"><span>Local</span><b>{e(typ)} · {e(level)}</b><span>Формируется</span><b>{e(forming)}</b><span>Структура</span><b>{e(structure_status)}</b><span>Цена</span><b>{e(_price(t.get("price")))}</b><span>Сделка</span><b>{e(state)}</b></div></article>')
    positions=[]
    for t in p.get("open_positions") or []:
        f=t.get("features") or {}
        margin=t.get("margin_usd",t.get("margin"))
        pnl=t.get("pnl_usdt",t.get("unrealized_pnl"))
        fraction=(float(pnl)/float(margin)*100) if _finite(pnl) is not None and _finite(margin) is not None and float(margin)>0 else None
        positions.append(f'<article><div class="heading"><b>{e(t.get("symbol"))}</b><strong class="{e(_side(t.get("side")).lower())}">{e(_side(t.get("side")))}</strong></div><div class="kv"><span>Маржа без плеча</span><b>{e(number(margin))} $</b><span>Плечо</span><b>{e(t.get("leverage"))}x</b><span>Вход / средняя</span><b>{e(_price(t.get("average_entry",t.get("entry"))))}</b><span>PnL</span><b class="{("long" if (pnl or 0)>=0 else "short")}">{e(money(pnl))} · {e(pct(fraction))}</b><span>ADD</span><b>{e(f.get("pyramid_level",0))}</b></div></article>')
    history=[]
    for t in (p.get("closed_trades") or [])[:30]:
        margin=t.get("margin",t.get("margin_usd")); pnl=t.get("pnl")
        percent=(float(pnl)/float(margin)*100) if _finite(pnl) is not None and _finite(margin) is not None and float(margin)>0 else None
        history.append(f'<article><div class="heading"><b>{e(t.get("symbol"))} · {e(_side(t.get("side")))}</b><strong class="{("long" if (pnl or 0)>=0 else "short")}">{e(money(pnl))}</strong></div><div class="kv"><span>PnL / маржа</span><b>{e(pct(percent))}</b><span>Вход → выход</span><b>{e(_price(t.get("entry")))} → {e(_price(t.get("exit")))}</b><span>Закрытие</span><b>{e(t.get("closed"))}</b><span>Причина</span><b>{e(t.get("reason"))}</b></div></article>')
    css="""*{box-sizing:border-box}html{background:#060b14;color:#e5efff;font:14px system-ui,-apple-system,sans-serif;overflow-x:hidden}body{margin:0;overflow-x:hidden}.app{width:100%;max-width:480px;margin:0 auto;padding:14px 12px 40px}h1{font-size:22px;margin:0}h2{font-size:15px;color:#b5c9e9;margin:24px 0 9px}small,.muted{color:#8ba4c6}.top{display:flex;justify-content:space-between;align-items:center;gap:8px}.status{color:#69e0bd;font-weight:700;font-size:11px}.stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin-top:14px}.stat,article{border:1px solid #20334e;background:#101b2b;border-radius:13px}.stat{padding:10px 7px;min-width:0}.stat strong{display:block;font-size:clamp(13px,3.6vw,19px);letter-spacing:-.6px;overflow-wrap:anywhere}.stat small{font-size:10px}article{padding:11px;margin:8px 0;min-width:0}.heading{display:flex;justify-content:space-between;align-items:center;gap:6px;font-size:15px}.kv{display:grid;grid-template-columns:minmax(0,40%) minmax(0,60%);gap:8px 5px;margin-top:10px;font-size:12px}.kv span{color:#91a9c9}.kv b{text-align:right;overflow-wrap:anywhere;font-weight:600}.long{color:#55e8a7}.short{color:#ff8798}.empty{color:#7085a5;background:#101827;padding:14px;border-radius:12px}footer{margin-top:24px;color:#7085a5;font-size:11px}"""
    return '<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta http-equiv="refresh" content="5"><style>'+css+'</style><title>PANDORA PAPER</title></head><body><main class="app"><header class="top"><div><h1>PANDORA</h1><small>BYBIT · PAPER ONLY</small></div><div style="text-align:right"><div class="status">● LIVE DATA</div><small>'+e(now.strftime("%d.%m.%Y %H:%M UTC"))+'</small><br><small>Работает: '+e(uptime)+'</small></div></header><section class="stats"><div class="stat"><small>БАЛАНС</small><strong>'+e(number(equity))+' $</strong></div><div class="stat"><small>PNL, $</small><strong>'+e(money(total))+'</strong></div><div class="stat"><small>PNL, %</small><strong>'+e(pct(total_pct))+'</strong></div></section><h2>DISCOVERY · TOP 5</h2>'+(''.join(sections) or '<p class="empty">Сканер ожидает рыночные данные</p>')+'<h2>ОТКРЫТЫЕ СДЕЛКИ</h2>'+(''.join(positions) or '<p class="empty">Открытых сделок нет</p>')+'<h2>ИСТОРИЯ СДЕЛОК</h2>'+(''.join(history) or '<p class="empty">Закрытых сделок пока нет</p>')+'<footer>PANDORA · монитор только для чтения · обновление 5 сек · без горизонтальной прокрутки</footer></main></body></html>'
