"""Read-only Strategy 1 monitor. All numbers come from the actual PAPER ledger."""
import html
import json
from datetime import datetime, timezone


def render(data):
    def esc(value):
        return html.escape(str(value if value is not None else '—'), quote=True)

    def num(value):
        return '—' if value is None else f'{float(value):,.4f}'

    def when(value):
        if value is None:
            return '—'
        try:
            return datetime.fromtimestamp(float(value) / 1000, timezone.utc).isoformat()
        except (ValueError, TypeError, OverflowError):
            return str(value)

    def table(headers, rows):
        return '<div class="scroll"><table><thead><tr>' + ''.join('<th>'+esc(x)+'</th>' for x in headers) + '</tr></thead><tbody>' + (''.join('<tr>'+''.join('<td>'+esc(c)+'</td>' for c in row)+'</tr>' for row in rows) or '<tr><td>Нет записей</td></tr>') + '</tbody></table></div>'

    primary = data.get('strategy1_primary') or {}
    engine = primary.get('engine') or {}
    health = data.get('health') or {}
    sources = data.get('sources') or {}
    details = engine.get('details') or {}
    durable = primary.get('h1_durable') or {}
    watches = primary.get('watch') or {}
    diagnostics = {r['symbol']: r for r in (data.get('strategy1_entry_diagnostics') or {}).get('tokens', [])}
    positions = primary.get('open_positions') or []
    position_map = {p['symbol']: p for p in positions}
    markets = []
    for symbol in data.get('local_experiment_symbols') or engine.get('symbols') or []:
        detail = details.get(symbol) or {}
        anchor = detail.get('h1_local') or durable.get(symbol) or {}
        flow = detail.get('flow_context') or {}
        watch = watches.get(symbol) or {}
        diag = diagnostics.get(symbol) or {}
        phase = (((position_map.get(symbol) or {}).get('features') or {}).get('pressure_state') or {}).get('phase') or (watch.get('context') or {}).get('phase') or 'Ожидание входа'
        states = [v.get('symbol_health', {}).get(symbol) for k,v in sources.items() if k.startswith('MarketTradeStream:')]
        tape = next((v for v in states if v), {})
        latency = ' / '.join(num(tape.get('latency_'+q+'_seconds')) for q in ('p50','p95','p99'))
        markets.append([symbol, anchor.get('pivot_type'), anchor.get('pivot_price'), when(anchor.get('pivot_candle_time')),
                        when(anchor.get('signal_candle_close_time')), anchor.get('confirmation_reason') or anchor.get('pivot_confirmation_policy'),
                        'LONG' if anchor.get('entry_side') == 1 else 'SHORT' if anchor.get('entry_side') == -1 else 'WAIT',
                        num(flow.get('buy_notional')), num(flow.get('sell_notional')), flow.get('pressure_phase'),
                        phase, (diag.get('executor_rejection') or {}).get('reason') or diag.get('reason') or detail.get('last_action') or 'Нет диагностического снимка',
                        num(tape.get('exchange_lag_seconds')), num(tape.get('receive_age_seconds')), latency])
    open_rows = []
    for p in positions:
        f = p.get('features') or {}
        open_rows.append([p.get('symbol'), p.get('side'), p.get('opened'), p.get('entry'), p.get('mark'), p.get('leverage'),
                          p.get('margin_usd'), p.get('unrealized_pnl'), (f.get('candidate_selection') or {}).get('reason'),
                          f.get('mfe_roe_pct'), f.get('mae_roe_pct'), f.get('mfe_giveback_move')])
    closed_rows = []
    for p in primary.get('closed_trades') or []:
        f = p.get('features') or {}
        closed_rows.append([p.get('closed'), p.get('symbol'), p.get('side'), p.get('entry'), p.get('exit'), p.get('pnl'),
                            (f.get('candidate_selection') or {}).get('reason'), p.get('reason'), f.get('entry_kind'),
                            f.get('mfe_roe_pct'), f.get('mae_roe_pct'), f.get('mfe_giveback_move')])
    legacy_open=[]
    legacy_positions=list(data.get('positions') or [])
    for account,book in (data.get('comparison_strategies') or {}).items():
        legacy_positions.extend({**row,'strategy':account} for row in book.get('positions') or [])
    for row in legacy_positions:
        legacy_open.append([row.get('strategy'),row.get('symbol'),row.get('side'),row.get('opened'),
                            row.get('entry'),row.get('mark'),row.get('unrealized_pnl')])
    token_rows=[];legacy_rows=[]
    totals=primary.get('token_totals')
    if totals is not None:
        canonical={row['symbol']:row for row in totals if row.get('account')=='strategy1'}
        symbols=list(dict.fromkeys(list(data.get('local_experiment_symbols') or [])+list(canonical)))
        for symbol in symbols:
            row=canonical.get(symbol) or {}
            realized=float(row.get('realized_pnl') or 0)
            opened=sum(float(p.get('unrealized_pnl') or 0) for p in positions if p.get('symbol')==symbol)
            token_rows.append([symbol,int(row.get('closed_trades') or 0),num(realized),num(opened),num(realized+opened)])
        legacy_rows=[[row.get('account'),row.get('symbol'),row.get('closed_trades'),num(row.get('realized_pnl'))]
                     for row in totals if row.get('account')!='strategy1']
    events=[]
    for event in (primary.get('events') or {}).get('events') or []:
        payload=event.get('payload') or {}
        events.append([event.get('recorded_at'),event.get('kind'),payload.get('symbol'),payload.get('side'),
                       payload.get('entry'),payload.get('exit'),payload.get('pnl'),payload.get('reason')])
    status = 'PAPER · данные подтверждены' if health.get('risk_ready') else 'PAPER · НЕ ГОТОВ / ПРОВЕРЬТЕ ДИАГНОСТИКУ'
    metrics = [('Equity $', primary.get('total_equity')), ('Realized PAPER PnL $', primary.get('realized_pnl')),
               ('Open PAPER PnL $', primary.get('unrealized_pnl')), ('Engine active', health.get('engine_active')),
               ('Checkpoint age s', health.get('checkpoint_age_seconds')), ('Market age s', health.get('market_age_seconds'))]
    cards = ''.join('<article><small>'+esc(k)+'</small><strong>'+esc(num(v) if isinstance(v,(int,float)) and not isinstance(v,bool) else v)+'</strong></article>' for k,v in metrics)
    state = {k:health.get(k) for k in ('healthy','risk_ready','engine_error','version')}
    state['Neon'] = sources.get('PersistentPostgres')
    state['history_error'] = data.get('history_error')
    state['history_updated_at'] = data.get('history_updated_at')
    state['LocalRisk'] = sources.get('LocalRisk')
    state['contract_constraints'] = sources.get('BybitInstruments')
    body = '<header><div><h1>PANDORA <span>Strategy 1</span></h1><p>'+esc(status)+'</p></div><a href="/api/dashboard">JSON / диагностика</a></header>'
    body += '<section class="cards">'+cards+'</section>'
    body += '<section><h2>PnL по токенам · вся история текущего счёта</h2><p>Закрытый PnL рассчитан по всем сохранённым сделкам, включая убытки и старые токены. Лимит строк на странице не ограничивает этот расчёт.</p>'
    body += (table(['Токен','Закрытий за всё время','Realized $','Open $','Суммарный $'],token_rows)
             if totals is not None else '<p>Исторические итоги ещё не получены; нулевой PnL не подставляется.</p>')+'</section>'
    body += '<section><h2>Сохранённые исторические журналы</h2><p>Отдельные прежние счета показаны без объединения с текущим балансом. Это предотвращает двойной учёт зеркальных сделок.</p>'+table(['Журнал','Токен','Закрытий','Исторический PnL $'],legacy_rows)+'</section>'
    body += '<section><h2>H1 → перевес → вход → затухание → выход → откат → перезаход</h2><p>Закрытые H1 свечи задают направление. Управление позицией — по исполненному потоку и реакции цены, без минутного окна. Положительный дисбаланс означает перевес покупателей, отрицательный — продавцов. MFE/MAE — только статистика.</p>'
    body += table(['Токен','H1 local','Цена локала','Время локала UTC','Подтверждение UTC','Основание','Разрешено','Покупки $','Продажи $','Состояние потока','Caterpillar','Блокирующий этап','Trade age s','Receive age s','Latency p50/p95/p99 s'],markets)+'</section>'
    body += '<section><h2>Открытые PAPER-позиции</h2>'+table(['Токен','Сторона','Открыта','Вход','Mark','Плечо','Маржа $','PnL $ net fees','Причина входа','MFE ROE %','MAE ROE %','Отдача движения'],open_rows)+'</section>'
    body += '<section><h2>Сохранённые позиции прежних счетов</h2>'+table(['Счёт','Токен','Сторона','Открыта','Вход','Наблюдаемая цена','PnL $'],legacy_open)+'</section>'
    body += '<section><h2>История фактических сделок</h2><p><a href="/strategy1/history">Весь архив · фильтр по токену · предыдущие страницы</a></p><p>Последние записи неизменяемого PAPER-журнала. PnL учитывает комиссию входа и выхода; модель исполнения по наблюдаемой цене, без моделирования проскальзывания и funding.</p>'+table(['Закрыта','Токен','Сторона','Вход','Выход','PnL $','Причина входа','Причина выхода','Вход / перезаход','MFE ROE %','MAE ROE %','Отдача движения'],closed_rows)+'</section>'
    body += '<section><h2>Журнал открытий и закрытий</h2><p><a href="/api/strategy1/events">Архив событий JSON</a></p>'+table(['Время','Событие','Токен','Сторона','Вход','Выход','PnL $','Причина'],events)+'</section>'
    body += '<section><h2>Движок · Render commit · Neon</h2><pre>'+esc(json.dumps(state,ensure_ascii=False,indent=2,default=str))+'</pre><p>Состояние API Render показывается только после отдельной проверки деплоя. Heartbeat приложения не подтверждает статус платформы Render.</p></section>'
    css = '''html{color-scheme:dark}*{box-sizing:border-box}body{margin:0;padding:18px;background:radial-gradient(circle at 15% 0,#10233d 0,transparent 32%),radial-gradient(circle at 90% 10%,#182336 0,transparent 28%),#050910;color:#e9f2ff;font:14px Inter,system-ui,-apple-system,sans-serif}body:before{content:"";position:fixed;inset:0;pointer-events:none;background-image:linear-gradient(rgba(55,221,255,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(55,221,255,.025) 1px,transparent 1px);background-size:32px 32px}main,header,#refreshStatus{position:relative;z-index:1;max-width:1600px;margin-left:auto;margin-right:auto}header{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:18px 22px;margin-bottom:16px;background:rgba(7,14,25,.88);border:1px solid #173b55;border-radius:18px;box-shadow:0 0 30px rgba(0,204,255,.07),inset 0 1px rgba(255,255,255,.03)}h1{margin:0;font-size:29px;letter-spacing:.12em;color:#f5fbff;text-shadow:0 0 18px rgba(72,217,255,.22)}h1 span{color:#44dcff;font-size:.62em;letter-spacing:.04em}h2{margin:0 0 12px;font-size:17px;color:#f1f7ff;letter-spacing:.02em}p,small{color:#89a4bf;line-height:1.55}a{color:#58dcff;text-decoration:none}a:hover{color:#c6f7ff}.cards{display:grid;grid-template-columns:repeat(6,minmax(150px,1fr));gap:12px;background:none!important;border:0!important;padding:0!important;margin-bottom:16px!important}.cards article,section{background:linear-gradient(145deg,rgba(13,26,43,.96),rgba(7,15,27,.96));border:1px solid #193b53;border-radius:16px;padding:18px;margin-bottom:16px;box-shadow:0 8px 30px rgba(0,0,0,.24),inset 0 1px rgba(255,255,255,.025)}.cards article{margin:0;min-height:105px;border-color:#20506d}.cards article:first-child{border-color:#a0d82d;box-shadow:0 0 24px rgba(166,229,45,.08)}.cards article:nth-child(2){border-color:#28c9f5}.cards small{display:block;text-transform:uppercase;letter-spacing:.08em;font-size:10px}.cards strong{display:block;margin-top:11px;font:700 24px ui-monospace,SFMono-Regular,Menlo,monospace;color:#f6fbff}.cards article:first-child strong{color:#c6ff45;text-shadow:0 0 16px rgba(198,255,69,.2)}.scroll{overflow:auto;border:1px solid #142d40;border-radius:12px;background:#07101b;scrollbar-color:#1f607d #07101b}table{border-collapse:collapse;width:100%;min-width:900px}th,td{text-align:left;padding:11px 12px;border-bottom:1px solid #132a3b;white-space:nowrap;font:11.5px ui-monospace,SFMono-Regular,Menlo,monospace}th{position:sticky;top:0;background:#0c1b2a;color:#68ddff;text-transform:uppercase;letter-spacing:.045em;z-index:1}tbody tr:hover{background:#0b2030}td:nth-child(1){color:#d8f5ff;font-weight:700}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#050b13;border:1px solid #15344a;border-radius:12px;padding:14px;color:#91dfff}#refreshStatus{font:11px ui-monospace,monospace;color:#8fda43;text-align:right;margin-top:0;margin-bottom:8px;text-transform:uppercase;letter-spacing:.08em}@media(max-width:1200px){.cards{grid-template-columns:repeat(3,1fr)}}@media(max-width:700px){body{padding:9px}header{display:block;padding:15px}.cards{grid-template-columns:1fr 1fr}.cards strong{font-size:18px}section{padding:13px}h1{font-size:23px}th,td{padding:9px;font-size:10.5px}}'''
    script = """<script>
let timer,refreshing=false;
async function refreshDashboard(){
 if(refreshing||document.visibilityState!=='visible')return;
 refreshing=true;const controller=new AbortController();const deadline=setTimeout(()=>controller.abort(),10000);
 try{const response=await fetch('/?refresh='+Date.now(),{cache:'no-store',signal:controller.signal});
 if(!response.ok)throw new Error('HTTP '+response.status);
 const incoming=new DOMParser().parseFromString(await response.text(),'text/html').getElementById('dashboardContent');
 if(!incoming)throw new Error('Нет данных монитора');
 const current=document.getElementById('dashboardContent');const scrolls=Array.from(current.querySelectorAll('.scroll')).map(el=>el.scrollLeft);
 current.replaceWith(document.importNode(incoming,true));document.querySelectorAll('#dashboardContent .scroll').forEach((el,i)=>el.scrollLeft=scrolls[i]||0);
 document.getElementById('refreshStatus').textContent='Обновлено '+new Date().toLocaleTimeString();
 }catch(error){document.getElementById('refreshStatus').textContent='Ошибка обновления: '+String(error);}
 finally{clearTimeout(deadline);refreshing=false;if(document.visibilityState==='visible')timer=setTimeout(refreshDashboard,5000);}
}
document.addEventListener('visibilitychange',()=>{clearTimeout(timer);if(document.visibilityState==='visible')refreshDashboard()});
timer=setTimeout(refreshDashboard,5000);
</script>"""
    return '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PANDORA Strategy 1</title><style>'+css+'</style><body><p id="refreshStatus">Данные монитора</p><main id="dashboardContent">'+body+'</main>'+script+'</body></html>'


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
