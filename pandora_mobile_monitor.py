"""Read-only, single-column PAPER monitor; no trading controls or hidden tabs."""
import html
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pandora_monitor import _summary, _tokens, _finite, _price, _side


def e(value):
    return html.escape(str('—' if value is None else value), quote=True)


def money(value):
    value=_finite(value)
    return '—' if value is None else f'{value:+,.2f} USDT'


def pct(value):
    value=_finite(value)
    return '—' if value is None else f'{value:+,.2f}%'


def local_text(value):
    value=value or {}
    return str(value.get('pivot_type') or 'WAIT')+' · '+_price(value.get('pivot_price'))


def local(token):
    state=token.get('local_state') or {}
    confirmed=token.get('confirmed_local') or state.get('confirmed_local') or {}
    active=token.get('execution_local') or state.get('execution_local') or confirmed
    forming=token.get('forming_local') or state.get('forming_local') or {}
    fresh=state.get('ready') and state.get('live_structure_fresh',True)
    blocked=state.get('entry_blocked',False)
    direction=_side(token.get('direction') or active.get('entry_side')) if fresh and not blocked else 'WAIT'
    return active,direction,forming,'STALE' if not fresh else 'BLOCKED' if blocked else 'CONFIRMED'


def card(title, subtitle, fields):
    return '<article><div class="heading"><b>'+e(title)+'</b><strong>'+e(subtitle)+'</strong></div><dl class="kv">'+''.join('<dt>'+e(k)+'</dt><dd>'+e(v)+'</dd>' for k,v in fields)+'</dl></article>'


def add_text(features):
    return '; '.join('ADD '+str(a.get('add_number'))+' · '+str(a.get('timestamp') or '—')+' · '+_price(a.get('price'))+' · '+money(a.get('added_margin')) for a in features.get('pyramid_adds') or []) or 'Нет'


def render(data):
    p=data.get('pandora') or {}; health=data.get('health') or {};sources=data.get('sources') or {}
    _,equity,total,total_pct=_summary(p)
    now=datetime.now(timezone.utc);started=p.get('started_at')
    uptime='—'
    try:
        sec=max(0,int((now-datetime.fromisoformat(str(started).replace('Z','+00:00'))).total_seconds()))
        uptime=f'{sec//3600} ч {(sec%3600)//60} мин'
    except (ValueError,TypeError):pass
    bybit='СВЕЖИЕ ДАННЫЕ' if any((r or {}).get('executed_flow') for r in (health.get('token_readiness') or {}).values()) else 'WAIT / STALE'
    db='OK' if health.get('engine_active') and not health.get('engine_error') and health.get('checkpoint_age_seconds') is not None and health['checkpoint_age_seconds']<15 else 'НЕ ПОДТВЕРЖДЕНО'
    top=card('PANDORA · PAPER ONLY','ГОТОВ' if health.get('risk_ready') else 'WAIT',[
        ('Баланс (реализованный)',money(p.get('realized_equity'))),('Equity с открытым PnL',money(equity)),
        ('Общий PnL',money(total)),('PnL от стартового капитала',pct(total_pct)),
        ('Время Самара',now.astimezone(ZoneInfo('Europe/Samara')).strftime('%d.%m.%Y %H:%M:%S UTC+4')),
        ('Работает',uptime),('Bybit',bybit),('PostgreSQL / checkpoint',db)])
    discovery=[]
    for t in _tokens(data)[:5]:
        state=t.get('local_state') or {};active,direction,forming,status=local(t)
        flow=t.get('flow_state') or {};decision=t.get('decision') or {}
        reason=decision.get('reason') if isinstance(decision,dict) else decision
        discovery.append(card(t.get('symbol'),direction,[
            ('Цена Mark',_price(t.get('price'))),('Последний H1 High',local_text(state.get('last_confirmed_high'))),
            ('Последний H1 Low',local_text(state.get('last_confirmed_low'))),
            ('Исторический H1',local_text(t.get('confirmed_local'))),('Активный H1/M15',local_text(active)),
            ('Формируется',local_text(forming)),('Структура',status),('Executed flow','FRESH' if flow.get('trade_data_fresh') else 'STALE'),
            ('BUY / SELL',money(flow.get('buy_notional'))+' / '+money(flow.get('sell_notional'))),
            ('Контроль входа / выхода',_side(flow.get('sustained_control_side'))+' / '+_side(flow.get('exit_control_side'))),
            ('Открытая позиция',_side((t.get('position') or {}).get('side')) if t.get('position') else 'НЕТ'),
            ('Решение / ожидание',reason or t.get('action_reason') or state.get('entry_block_reason'))]))
    positions=[]
    for t in p.get('open_positions') or []:
        f=t.get('features') or {};margin=t.get('margin_usd',t.get('margin'));pnl=t.get('pnl_usdt',t.get('unrealized_pnl'))
        percent=float(pnl)/float(margin)*100 if _finite(pnl) is not None and _finite(margin) and float(margin)>0 else None
        positions.append(card(t.get('symbol'),_side(t.get('side')),[
            ('Первый вход',_price(f.get('original_entry',t.get('entry')))),('Время входа',t.get('opened')),
            ('Средняя цена',_price(t.get('average_entry',t.get('entry')))),('Текущая цена Mark',_price(t.get('mark'))),
            ('Маржа без плеча',money(margin)),('Плечо / эффективное',str(t.get('leverage'))+'x / '+str(t.get('effective_leverage'))+'x'),
            ('Текущий net PnL',money(pnl)),('PnL от маржи',pct(percent)),('Доливки',f.get('pyramid_level',0)),
            ('MFE / %',money(f.get('peak_mfe_usd'))+' / '+pct(f.get('peak_mfe_pct'))),
            ('MFE после последней доливки',money(f.get('segment_mfe_usd'))),('Отдано от MFE',money(f.get('mfe_giveback_usd'))),
            ('Сопровождение',(f.get('exit_decision') or {}).get('reason') or 'WAIT FRESH FLOW'),
            ('Подтверждение контроля',(f.get('exit_control_state') or {}).get('phase')),('История ADD',add_text(f))]))
    history=[]
    for t in p.get('closed_trades') or []:
        f=t.get('features') or {};margin=t.get('margin');pnl=t.get('pnl');peak=_finite(f.get('peak_mfe_usd'))
        percent=float(pnl)/float(margin)*100 if _finite(pnl) is not None and _finite(margin) and float(margin)>0 else None
        giveback=(peak-float(pnl))/peak*100 if peak and peak>0 and _finite(pnl) is not None else None
        history.append(card(str(t.get('symbol'))+' · '+_side(t.get('side')),money(pnl),[
            ('Открытие',t.get('opened')),('Закрытие',t.get('closed')),('Средний вход → выход',_price(t.get('entry'))+' → '+_price(t.get('exit'))),
            ('Маржа',money(margin)),('Плечо',str(t.get('leverage'))+'x'),('Net PnL от маржи',pct(percent)),
            ('MFE',money(peak)),('Доля отданного MFE',pct(giveback)),('Причина выхода',t.get('reason')),('История ADD',add_text(f))]))
    css='''*{box-sizing:border-box}html{background:#060b14;color:#e5efff;font:14px system-ui,sans-serif}body{margin:0}.app{width:100%;max-width:480px;margin:auto;padding:12px}h1,h2{font-size:18px}article{border:1px solid #20334e;background:#101b2b;border-radius:12px;padding:12px;margin:10px 0;min-width:0}.heading{display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px;overflow-wrap:anywhere}.kv{display:grid;grid-template-columns:minmax(0,40fr) minmax(0,60fr);gap:8px;margin:12px 0 0;font-size:12px}.kv dt{color:#91a9c9}.kv dd{margin:0;text-align:right;overflow-wrap:anywhere;min-width:0}footer,.empty{color:#91a9c9;font-size:12px}'''
    empty='<p class="empty">Нет данных / сделок</p>'
    body=top+'<h2>DISCOVERY · TOP 5</h2>'+(''.join(discovery) or empty)+'<h2>ОТКРЫТЫЕ СДЕЛКИ</h2>'+(''.join(positions) or empty)+'<h2>ИСТОРИЯ СДЕЛОК</h2>'+(''.join(history) or empty)
    # Reload preserves the reading position in sessionStorage; every response is escaped server-side.
    script="""<script>try{const y=sessionStorage.getItem('pandora-scroll');if(y)scrollTo(0,Number(y));addEventListener('pagehide',()=>sessionStorage.setItem('pandora-scroll',String(scrollY)));}catch{}setTimeout(()=>location.reload(),5000);</script>"""
    return '<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>PANDORA PAPER</title><style>'+css+'</style></head><body><main class="app">'+body+'<footer>PAPER ONLY · только чтение · обновление 5 секунд</footer></main>'+script+'</body></html>'
