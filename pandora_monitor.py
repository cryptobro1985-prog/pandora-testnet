"""Responsive, read-only Pandora Win PAPER terminal with incremental JSON updates."""
import html
import json
import math
from urllib.parse import urlencode


def _e(value):
    return html.escape(str('—' if value is None else value), quote=True)


def _finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _n(value, digits=4):
    number = _finite(value)
    return f'{number:,.{digits}f}' if number is not None else '—'


def _price(value):
    number = _finite(value)
    digits = 4 if number is None or abs(number) >= 1 or number == 0 else min(12, max(6, math.ceil(-math.log10(abs(number))) + 5))
    return _n(value, digits)


def _mark_status(token):
    age = _finite(token.get('price_age_seconds'))
    if token.get('mark_fresh') is False or _finite(token.get('price')) is None:
        return ('WAIT FIRST MARK' if _finite(token.get('price')) is None else 'STALE · возраст неизвестен') if age is None else 'STALE · '+_n(age, 1)+' s'
    return 'FRESH · '+_n(age, 1)+' s' if token.get('mark_fresh') is True and age is not None else 'Возраст mark не передан'


def _exit_state(features):
    phase = (features.get('exit_control_state') or {}).get('phase')
    return {'UNKNOWN':'НЕТ СВЕЖЕГО FLOW','PAUSED':'ПОДТВЕРЖДЕНИЕ ПРИОСТАНОВЛЕНО',
            'OBSERVING':'НАБЛЮДАЕМ КОНТРКОНТРОЛЬ','CONFIRMED':'КОНТРКОНТРОЛЬ ПОДТВЕРЖДЁН',
            'HOLD':'УДЕРЖАНИЕ'}.get(phase, phase or '—')


def _local_symbols(data):
    primary = data.get('pandora') or {}
    details = (primary.get('engine') or {}).get('details') or {}
    active = [p.get('symbol') for p in primary.get('open_positions') or []]
    active += [t.get('symbol') for t in primary.get('tokens') or []]
    active += list(data.get('pandora_symbols') or []) + list(details)
    if not any(active):active = list(primary.get('h1_durable') or {})
    return list(dict.fromkeys(s for s in active if s))[:100]


def _m(value):
    number = _finite(value)
    return f'{number:+,.4f} USDT' if number is not None else '—'


def _pct(value):
    number = _finite(value)
    return f'{number:+,.2f}%' if number is not None else '—'


def _side(value):
    return 'LONG' if value in (1, '1', 'LONG', 'long') else 'SHORT' if value in (-1, '-1', 'SHORT', 'short') else 'WAIT'


def _tone(value):
    number = _finite(value)
    return 'positive' if number is not None and number > 0 else 'negative' if number is not None and number < 0 else 'neutral'


def _field(name, value, kind=''):
    return '<span data-field="'+_e(name)+'" class="'+_e(kind)+'">'+_e(value)+'</span>'


def _metric(label, name, value, kind=''):
    return '<div class="metric"><dt>'+_e(label)+'</dt><dd>'+_field(name, value, kind)+'</dd></div>'


def _card(key, title, subtitle, metrics, kind='', fields=None):
    fields = fields or ('title', 'subtitle')
    return '<article class="terminal-card '+_e(kind)+'" data-key="'+_e(key)+'"><div class="card-heading"><h3>'+_field(fields[0], title)+'</h3><small>'+_field(fields[1], subtitle)+'</small></div><dl class="metric-grid">'+''.join(_metric(*m) for m in metrics)+'</dl></article>'


def _local_text(local):
    if not isinstance(local, dict) or not local.get('pivot_type'):
        return '—'
    return str(local['pivot_type'])+' · '+_price(local.get('pivot_price'))



def _execution_text(local):
    text = _local_text(local)
    return text+' · '+str(local.get('confirmation_source') or local.get('interval') or 'H1') if text != '—' else text


def _scanner_quote(token):
    return _price(token.get('scanner_price'))+' · '+_n(token.get('scanner_price_age_seconds'), 1)+' s' if _finite(token.get('scanner_price')) is not None else '—'


def _position_data(position):
    features = position.get('features') or {}
    current = position.get('current_local') or features.get('local_state') or {}
    entry_local = position.get('entry_local') or features.get('entry_local') or features.get('confirmed_local') or features
    confirmed = current.get('confirmed_local') or current
    forming = current.get('forming_local') or ({'pivot_type': current.get('pending_pivot_type'),
               'pivot_price': current.get('pending_pivot_price')} if current.get('pending_pivot_type') else {})
    margin = position.get('margin_usd', position.get('margin'))
    pnl = position.get('pnl_usdt', position.get('unrealized_pnl'))
    percent = position.get('pnl_percent') if 'pnl_percent' in position else (
        float(pnl)/float(margin)*100 if _finite(pnl) is not None and _finite(margin) and float(margin) > 0 else None)
    return dict(original_entry=position.get('entry_price', position.get('original_entry',
                    features.get('original_entry', position.get('entry')))),
                average_entry=position.get('average_entry', position.get('entry')),
                entry_time=position.get('entry_time', position.get('opened')),
                entry_local=entry_local, current_confirmed=confirmed, current_forming=forming,
                current_execution=current.get('execution_local') or confirmed,
                pnl=pnl, percent=percent, margin=margin)


def _decision_text(decision=None, state=None):
    if isinstance(decision, dict):
        decision = decision.get('action') or decision.get('status') or decision.get('decision')
    value = str(decision or state or 'WAIT').upper()
    return {'HOLD':'ПОЗИЦИЯ ОТКРЫТА', 'ENTRY': 'ВХОД', 'ENTER': 'ВХОД', 'ENTRY_LONG': 'ВХОД LONG', 'ENTER_LONG': 'ВХОД LONG',
            'ENTRY_SHORT': 'ВХОД SHORT', 'ENTER_SHORT': 'ВХОД SHORT', 'WAIT': 'ЖДЁМ',
            'WAIT_DATA': 'ЖДЁМ ДАННЫЕ', 'WAIT_REENTRY': 'ЖДЁМ ПЕРЕЗАХОД', 'SCANNING': 'СКАНИРОВАНИЕ',
            'SELECTED': 'ЖДЁМ ПОДТВЕРЖДЕНИЯ', 'LONG_READY': 'ЖДЁМ ВХОД LONG',
            'SHORT_READY': 'ЖДЁМ ВХОД SHORT', 'LONG': 'ПОЗИЦИЯ LONG', 'SHORT': 'ПОЗИЦИЯ SHORT'}.get(value, value)


def _startup_view(primary):
    startup = primary.get('startup') or {}
    stage = str(startup.get('stage') or 'WAIT_DATA').upper()
    status = str(startup.get('status') or 'WAITING').upper()
    stages = {'WAIT_LEASE':'Ожидание PAPER-счёта','WAIT_CONTRACTS':'Загрузка контрактов Bybit','SCANNING_MARKET':'Обзор всего рынка Bybit','ANALYSING_SELECTED':'Анализ выбранной пятёрки','WAITING_ACTIVE_CANDIDATES':'Поиск активных кандидатов','WAIT_SCANNER':'Ожидание свежего обзора',
        'RESTORING': 'Восстановление PAPER-состояния', 'RESTORE': 'Восстановление PAPER-состояния',
        'BOOTSTRAP': 'Первичный обзор Bybit', 'METADATA': 'Загрузка контрактов Bybit',
        'CONTRACTS': 'Загрузка контрактов Bybit', 'TICKERS': 'Обзор всего рынка Bybit',
        'DISCOVERY': 'Выбор активной пятёрки', 'SCANNING': 'Обзор всего рынка Bybit',
        'HISTORY': 'Подготовка H1 / M15', 'H1': 'Подготовка H1 / M15',
        'FLOW_WARMUP': 'Наблюдение исполненных BUY / SELL', 'WARMING': 'Наблюдение исполненных BUY / SELL',
        'ANALYZING': 'Анализ пяти выбранных токенов', 'DECIDING': 'Решения: вход или ожидание',
        'READY': 'Первичный анализ завершён', 'RUNNING': 'Непрерывный анализ рынка',
        'WAIT_DATA': 'Ожидание свежих данных Bybit'}
    statuses = {'READY': 'ГОТОВО', 'RUNNING': 'РАБОТАЕТ', 'WAITING': 'ЖДЁМ', 'WARMING': 'ПРОГРЕВ ДАННЫХ',
                'PENDING': 'ПОДГОТОВКА', 'FAILED': 'НЕТ ДАННЫХ', 'ERROR': 'НЕТ ДАННЫХ', 'BLOCKED': 'ЖДЁМ'}
    reason = startup.get('reason') or startup.get('message') or 'Вход разрешён только после свежей структуры и исполненных сделок.'
    return stages.get(stage, stage), statuses.get(status, status), reason

def _token_view(token):
    flow = token.get('flow_state') or {}
    position = token.get('position') or {}
    features = position.get('features') or {}
    risk = features.get('risk_plan') or {}
    direction = _side(token.get('direction'))
    detail = _position_data(position)
    pnl = detail['pnl'] if position else token.get('current_pnl_usd')
    percent = detail['percent'] if position else token.get('current_pnl_pct')
    decision = token.get('decision')
    decision_reason = decision.get('reason') if isinstance(decision, dict) else None
    return token.get('symbol'), 'RANK '+str(token.get('rank', '—'))+' · '+str(token.get('state') or direction), [
        ('Цена', 'price', _price(token.get('price'))),
        ('Mark / данные', 'mark_status', _mark_status(token)),
        ('Scanner quote / возраст', 'scanner_quote', _scanner_quote(token)),
        ('Scanner score', 'score', _n(token.get('pandora_win_score'))),
        ('Исторический confirmed H1', 'confirmed', _local_text(token.get('confirmed_local'))),
        ('Активный local H1/M15', 'execution', _execution_text(token.get('execution_local') or (token.get('local_state') or {}).get('execution_local') or token.get('confirmed_local'))),
        ('Формирующийся local', 'forming', _local_text(token.get('forming_local'))),
        ('Направление', 'direction', direction),
        ('Позиция', 'position', _side(position.get('side'))),
        ('BUY volume', 'buy', _m(token.get('buy_volume'))),
        ('SELL volume', 'sell', _m(token.get('sell_volume'))),
        ('Flow imbalance', 'imbalance', _pct(_finite(token.get('flow_imbalance'))*100 if _finite(token.get('flow_imbalance')) is not None else None)),
        ('Объём / сек.', 'velocity', _n(token.get('volume_velocity'))),
        ('Tape', 'tape', 'FRESH' if flow.get('trade_data_fresh') else 'STALE'),
        ('Контроль входа', 'control', _side(flow.get('sustained_control_side'))),
        ('Быстрый контроль выхода', 'fast_control', _side(flow.get('fast_control_side'))),
        ('Контроль закрытия', 'exit_control', _side(flow.get('exit_control_side', flow.get('fast_control_side')))),
        ('Основание контроля', 'exit_basis', flow.get('exit_control_basis')),
        ('Подтверждение выхода', 'exit_state', _exit_state(features)),
        ('Причина удержания / выхода', 'exit_reason', (features.get('exit_decision') or {}).get('reason')),
        ('Минутный контекст', 'context_control', _side(flow.get('context_control_side'))),
        ('Цена первого входа', 'original_entry', _price(detail['original_entry'])),
        ('Время входа', 'entry_time', detail['entry_time']),
        ('Local при входе', 'entry_local', _local_text(detail['entry_local'])),
        ('Average entry', 'entry', _price(detail['average_entry'] if position else token.get('average_entry'))),
        ('Маржа', 'margin', _m(token.get('margin'))),
        ('Notional', 'notional', _m(token.get('notional'))),
        ('Плечо / ADD', 'leverage', str(token.get('leverage') or '—')+'x / '+str(token.get('pyramid_level', 0))),
        ('Эффективное плечо', 'effective_leverage', _n(position.get('effective_leverage'))+'x'),
        ('PnL · USDT', 'pnl', _m(pnl), _tone(pnl)),
        ('PnL / маржа', 'pnl_pct', _pct(percent), _tone(percent)),
        ('Peak MFE', 'mfe', _m(token.get('mfe'))),
        ('MAE', 'mae', _m(token.get('mae'))),
        ('MFE giveback', 'giveback', _m(token.get('mfe_giveback'))),
        ('Ориентир модели (не SL)', 'stop', _price(risk.get('stop_price'))),
        ('Решение', 'decision', _decision_text(decision, token.get('state'))),
        ('Последнее действие', 'action', token.get('last_action')),
        ('Причина', 'reason', token.get('action_reason') or decision_reason),
    ]


def _position_view(position):
    f = position.get('features') or {}
    detail = _position_data(position)
    pnl, margin, percent = detail['pnl'], detail['margin'], detail['percent']
    risk = f.get('risk_plan') or {}
    return str(position.get('symbol'))+' · '+_side(position.get('side')), detail['entry_time'], [
        ('Цена первого входа', 'original_entry', _price(detail['original_entry'])),
        ('Время входа', 'entry_time', detail['entry_time']),
        ('Average entry', 'entry', _price(detail['average_entry'])), ('Mark', 'mark', _price(position.get('mark'))),
        ('Local при входе', 'entry_local', _local_text(detail['entry_local'])),
        ('Исторический confirmed H1', 'current_confirmed', _local_text(detail['current_confirmed'])),
        ('Активный local H1/M15', 'current_execution', _execution_text(detail['current_execution'])),
        ('Текущий forming local', 'current_forming', _local_text(detail['current_forming'])),
        ('PnL · USDT', 'pnl', _m(pnl), _tone(pnl)), ('PnL / маржа', 'pnl_pct', _pct(percent), _tone(percent)),
        ('Маржа', 'margin', _m(margin)), ('Notional', 'notional', _m(position.get('notional_usd', position.get('notional')))),
        ('Плечо', 'leverage', str(position.get('leverage') or '—')+'x'), ('Эффективное плечо', 'effective_leverage', _n(position.get('effective_leverage'))+'x'), ('ADD level', 'level', f.get('pyramid_level', 0)),
        ('Peak MFE', 'mfe', _m(f.get('peak_mfe_usd'))), ('MAE', 'mae', _m(f.get('mae_usd'))),
        ('MFE giveback', 'giveback', _m(f.get('mfe_giveback_usd'))), ('Ориентир модели (не SL)', 'stop', _price(risk.get('stop_price'))),
        ('Подтверждение выхода', 'exit_state', _exit_state(f)),
        ('Причина удержания / выхода', 'exit_reason', (f.get('exit_decision') or {}).get('reason')),
    ]


def _trade_view(trade):
    f = trade.get('features') or {}
    pnl = trade.get('pnl'); margin = trade.get('margin', trade.get('margin_usd'))
    percent = float(pnl)/float(margin)*100 if _finite(pnl) is not None and _finite(margin) and float(margin) > 0 else None
    return str(trade.get('symbol'))+' · '+_side(trade.get('side')), trade.get('closed'), [
        ('Первый вход', 'original_entry', _price(trade.get('entry_price',f.get('original_entry',f.get('entry_mark',trade.get('entry')))))),
        ('Время входа', 'entry_time', trade.get('entry_time',trade.get('opened'))),
        ('Local при входе', 'entry_local', _local_text(trade.get('entry_local') or f)),
        ('Средний вход', 'entry', _price(trade.get('entry'))), ('Выход', 'exit', _price(trade.get('exit'))),
        ('PnL', 'pnl', _m(pnl), _tone(pnl)), ('PnL / маржа', 'pnl_pct', _pct(percent), _tone(percent)),
        ('Маржа', 'margin', _m(margin)), ('Плечо', 'leverage', str(trade.get('leverage') or '—')+'x'),
        ('Тип входа', 'kind', f.get('entry_kind')), ('Причина выхода', 'reason', trade.get('reason')),
        ('Peak MFE', 'mfe', _m(f.get('peak_mfe_usd'))), ('Giveback', 'giveback', _m(f.get('mfe_giveback_usd'))),
    ]


def _tokens(data):
    primary = data.get('pandora') or {}
    if primary.get('tokens'):
        return primary['tokens']
    discovery = data.get('discovery') or {}
    details = (primary.get('engine') or {}).get('details') or {}
    source = primary.get('h1_durable') or {}
    selected = {t.get('symbol'): t for t in discovery.get('selected') or []}
    # Bootstrap still exposes locals before a scanner row or position exists.
    symbols = discovery.get('selected_symbols') or []
    return [{**selected.get(s, {}), 'symbol': s, 'confirmed_local': (details.get(s) or {}).get('h1_local') or source.get(s) or {},
             'flow_state': (details.get(s) or {}).get('flow_context') or {}, 'state': 'SCANNING'} for s in symbols]


def _collection(name, entries, empty):
    return '<div id="'+name+'" class="card-grid">'+''.join(entries)+'</div><p id="'+name+'-empty" class="empty"'+(' hidden' if entries else '')+'>'+_e(empty)+'</p>'


def _json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _summary(primary):
    start = _finite(primary.get('starting_equity', 500))
    equity = _finite(primary.get('total_equity'))
    realized = _finite(primary.get('realized_pnl')); unreal = _finite(primary.get('unrealized_pnl'))
    total = realized+unreal if realized is not None and unreal is not None else None
    percent = total/start*100 if total is not None and start and start > 0 else None
    return start, equity, total, percent


def _shell(body, script=''):
    return '<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#080b18"><title>Pandora Win · PAPER terminal</title><style>'+CSS+'</style></head><body><main class="terminal">'+body+'</main>'+script+'</body></html>'


def render(data):
    p = data.get('pandora') or {}; health = data.get('health') or {}
    account = p.get('account') or {}; risk = p.get('risk') or {}; valuation = p.get('margin_valuation') or {}
    start, equity, total, percent = _summary(p)
    status = 'PAPER ГОТОВ' if health.get('risk_ready') else 'НЕ ГОТОВ'
    reason = risk.get('reason') or health.get('engine_error') or next(iter((health.get('execution_errors') or {}).values()), None) or ('PORTFOLIO_MARKS_STALE' if valuation.get('complete') is False else 'Ожидание актуальных данных / проверки исполнителя' if not health.get('risk_ready') else 'Fresh market data · PAPER only')
    body = '<header class="masthead"><div><p class="eyebrow">BYBIT USDT PERPETUAL · PAPER TERMINAL</p><h1>Pandora <span>'+('Pump V3' if p.get('experiment_id')=='PANDORA_PUMP_STRUCTURE_V3_400' else 'Flow V2' if p.get('flow_v2') else 'Win')+'</span><b class="brand-mark">✦</b></h1><p class="brand-sub">EXECUTED FLOW / HOURLY TOP-5 / CAPITAL CONTROL</p></div><div class="connection"><span class="mode">PAPER ONLY</span><strong id="readiness" class="'+('positive' if health.get('risk_ready') else 'warning')+'">'+_e(status)+'</strong><small id="connection-state" role="status" aria-live="polite">JSON · обновление каждую секунду</small><small id="update-time">'+_e(data.get('snapshot_at'))+'</small></div></header>'
    startup_stage, startup_status, startup_reason = _startup_view(p)
    body += '<section class="startup-panel" aria-label="Первичный обзор рынка"><b>ЗАПУСК / ПЕРВИЧНЫЙ ОБЗОР</b><div class="startup-grid"><strong id="startup-stage">'+_e(startup_stage)+'</strong><span id="startup-status">'+_e(startup_status)+'</span></div><p id="startup-reason">'+_e(startup_reason)+'</p></section>'
    body += '<section class="account-panel" aria-labelledby="account-title"><div class="section-head"><h2 id="account-title">Общий счёт</h2><span class="tag">USDT · только фактический PAPER PnL</span></div><div class="account-grid">'
    for label, key, value, kind in [
        ('CURRENT EQUITY', 'equity', _m(equity), ''), ('TOTAL PnL · USDT', 'total-pnl', _m(total), _tone(total)),
        ('TOTAL PnL · % ОТ СТАРТА', 'total-pct', _pct(percent), _tone(percent)), ('START EQUITY', 'start', _m(start), ''),
        ('REALIZED PnL', 'realized', _m(p.get('realized_pnl')), _tone(p.get('realized_pnl'))),
        ('UNREALIZED PnL', 'unrealized', _m(p.get('unrealized_pnl')), _tone(p.get('unrealized_pnl'))),
        ('MAX EQUITY', 'max-equity', _m(p.get('max_equity')), ''), ('CURRENT EXPOSURE', 'exposure', _m(p.get('current_exposure')), ''),
        ('FREE MARGIN', 'free-margin', _m(account.get('free_margin')), ''), ('USED MARGIN', 'used-margin', _m(account.get('used_margin')), ''),
    ]:
        body += '<article class="account-tile"><small>'+_e(label)+'</small><strong id="account-'+key+'" class="'+kind+'">'+_e(value)+'</strong></article>'
    body += '</div><div id="risk-banner" class="risk-banner"><b>RISK / DATA</b><span id="risk-reason">'+_e(reason)+'</span></div><p class="sub">Доходность счёта считается от стартового equity. PnL позиции и сделки в процентах — от её маржи. Убыточные результаты не скрываются.</p></section>'
    body += '<nav class="tabs" aria-label="Разделы терминала"><button type="button" data-tab="discovery" aria-pressed="true">Discovery <span id="count-discovery">'+str(len(_tokens(data)))+'</span></button><button type="button" data-tab="positions" aria-pressed="false">Позиции <span id="count-positions">'+str(len(p.get('open_positions') or []))+'</span></button><button type="button" data-tab="history" aria-pressed="false">История</button><button type="button" data-tab="audit" aria-pressed="false">Действия / ADD</button></nav>'
    body += '<section id="panel-discovery" class="tab-panel" aria-labelledby="discovery-title"><div class="section-head"><div><p class="eyebrow">LIVE DISCOVERY</p><h2 id="discovery-title">Токены под наблюдением</h2></div><button type="button" class="secondary" id="sort-rank">По текущему rank ↗</button></div><p class="sub">Rank обновляется в карточке. Порядок карточек сохраняется; сортировка меняется только по вашей кнопке.</p>'
    cards = [_card(t.get('symbol'), *_token_view(t), kind='token-card') for t in _tokens(data)]
    body += _collection('tokens', cards, 'Scanner ожидает свежие рыночные данные. Отсутствующие токены не подставляются.')
    candidates=(data.get('discovery') or {}).get('top_movers') or []
    body+='<details class="scanner-details"><summary>Scanner · все кандидаты <span id="count-candidates">'+str(len(candidates))+'</span></summary>'
    candidate_cards=[]
    for t in candidates:
        candidate_cards.append(_card(t.get('symbol'),str(t.get('symbol')),'RANK '+str(t.get('rank','—')),[
            ('Score','score',_n(t.get('pandora_win_score'))),('Цена','price',_price(t.get('last'))),
            ('Текущий импульс %','move',_pct(t.get('scan_return_pct'))),('Turnover / мин.','turnover',_m(t.get('turnover_per_minute'))),
            ('BUY USD','buy',_m(t.get('buy_volume'))),('SELL USD','sell',_m(t.get('sell_volume'))),
            ('Trades / сек.','trades',_n(t.get('trade_velocity'))),('Executed tape','tape','FRESH' if t.get('flow_fresh') else 'WARMING / STALE')]))
    body+=_collection('candidates',candidate_cards,'Пул кандидатов ещё не сформирован.')+'</details>'
    if not p.get('flow_v2'):
        details=(p.get('engine') or {}).get('details') or {};durable=p.get('h1_durable') or {}
        symbols=_local_symbols(data)
        body+='<details class="scanner-details"><summary>Локалы текущего наблюдения (до 100) <span id="count-locals">'+str(len(symbols))+'</span></summary>'
        local_cards=[]
        for symbol in symbols:
            local_state=(details.get(symbol) or {}).get('h1_local') or durable.get(symbol) or {}
            confirmed=local_state.get('confirmed_local') or local_state
            forming=local_state.get('forming_local') or ({'pivot_type':local_state.get('pending_pivot_type'),'pivot_price':local_state.get('pending_pivot_price')} if local_state.get('pending_pivot_type') else {})
            local_cards.append(_card(symbol,symbol,_side(local_state.get('entry_side')),[
                ('Confirmed local','confirmed',_local_text(confirmed)),('Forming local','forming',_local_text(forming)),
                ('Разрешение входа','entry_state','BLOCKED' if local_state.get('entry_blocked') else 'READY' if local_state.get('ready') else 'WAIT'),
                ('Причина','reason',local_state.get('entry_block_reason') or local_state.get('reason') or local_state.get('confirmation_source'))]))
        body+=_collection('locals',local_cards,'Наблюдений локальной структуры пока нет.')+'</details></section>'
    else:
        body+='</section>'
    body += '<section id="panel-positions" class="tab-panel" hidden><div class="section-head"><h2>Открытые позиции</h2><span class="tag">Включая токены вне Discovery</span></div>'
    body += _collection('positions', [_card(str(t.get('symbol'))+':'+str(t.get('opened')), *_position_view(t), kind='position-card') for t in p.get('open_positions') or []], 'Открытых позиций нет.')+'</section>'
    body += '<section id="panel-history" class="tab-panel" hidden><div class="section-head"><h2>Закрытые сделки</h2><a class="secondary" href="/pandora/history">Полная история ↗</a></div>'
    body += _collection('trades', [_card(str(t.get('id', str(t.get('symbol'))+':'+str(t.get('opened'))+':'+str(t.get('closed')))), *_trade_view(t), kind='trade-card') for t in (p.get('closed_trades') or [])[:30]], 'Закрытых сделок пока нет.')
    if p.get('token_totals') is None:
        body += '<p class="sub">Агрегаты недоступны; нулевой PnL не подставляется.</p>'
    body += '</section>'
    body += '<section id="panel-audit" class="tab-panel" hidden><div class="section-head"><h2>PYRAMID ADDS</h2><span class="tag">Каждая доливка записана отдельно</span></div>'
    adds = []
    for add in p.get('pyramid_adds') or []:
        adds.append(_card(str(add.get('symbol'))+':'+str(add.get('opened'))+':'+str(add.get('add_number')), str(add.get('symbol'))+' · ADD '+str(add.get('add_number')), add.get('timestamp'), [
            ('Цена', 'price', _price(add.get('price'))), ('Average entry', 'average', _price(add.get('average_entry'))),
            ('Added margin', 'margin', _m(add.get('added_margin'))), ('Added notional', 'notional', _m(add.get('added_notional'))),
            ('MFE до ADD', 'before', _m(add.get('mfe_before_add'))), ('MFE после ADD', 'after', _m(add.get('mfe_after_add')))]))
    body += _collection('adds', adds, 'Доливок пока нет.')+'<h3 class="section-caption">RE-ENTRY / REVERSAL / ROTATION / AUDIT</h3>'
    event_cards = []
    for e in ((p.get('events') or {}).get('events') or [])[:40]:
        payload = e.get('payload') or {}
        event_cards.append(_card(str(e.get('id')), e.get('kind'), e.get('recorded_at'), [('Токен', 'symbol', payload.get('symbol')), ('Причина', 'reason', payload.get('reason'))], kind='event-card'))
    body += _collection('events', event_cards, 'Журнал действий пока пуст.')+'</section>'
    body += '<footer><span>Pandora Win · PAPER ONLY</span><a href="/api/pandora">JSON API для ChatGPT ↗</a><a href="/api/pandora/events">Журнал API ↗</a><a href="/health/risk">Risk readiness ↗</a></footer>'
    # JSON is consumed as text, never evaluated. Escape all HTML-significant chars
    # so a symbol/reason cannot terminate the script element.
    bootstrap_data = {**data, 'pandora': {k:v for k,v in p.items() if k != 'token_totals'}}
    bootstrap = json.dumps(_json_safe(bootstrap_data), ensure_ascii=False, default=str, allow_nan=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    return _shell(body, '<script type="application/json" id="initial-state">'+bootstrap+'</script><script>'+SCRIPT+'</script>')


def render_history(page):
    args = {}
    if page.get('symbol'):
        args['symbol'] = page['symbol']
    links = '<a class="secondary" href="/">← Pandora Win</a><a class="secondary" href="/pandora/history?'+_e(urlencode(args))+'">Новейшие сделки</a>'
    if page.get('next_before_id') is not None:
        links += '<a class="secondary" href="/pandora/history?'+_e(urlencode({**args, 'before': page['next_before_id']}))+'">Более ранние сделки →</a>'
    cards = [_card(str(t.get('id')), *_trade_view(t), kind='trade-card') for t in page.get('trades') or []]
    body = '<header class="masthead"><div><p class="eyebrow">PANDORA WIN · PAPER LEDGER</p><h1>Pandora <span>Win</span></h1><h2>Полная история сделок</h2></div><span class="mode">PAPER ONLY</span></header><nav class="history-links">'+links+'</nav>'+_collection('trades', cards, 'Сделок по этому фильтру нет.')+'<nav class="history-links">'+links+'</nav>'
    return _shell(body)


CSS = r'''
.startup-panel{margin:0 0 20px;padding:14px 18px;border:1px solid var(--line);border-radius:14px;background:linear-gradient(120deg,#171934,#102533);min-height:112px}.startup-panel>b{font-size:10px;letter-spacing:.09em;color:var(--violet)}.startup-grid{display:flex;justify-content:space-between;gap:15px;flex-wrap:wrap;margin:6px 0;font-size:14px}.startup-grid strong{color:var(--cyan)}.startup-grid span{color:var(--yellow);font-weight:700}.startup-panel p{font-size:12px;color:var(--muted);overflow-wrap:anywhere}
:root{color-scheme:dark;--bg:#080b18;--panel:#11182a;--text:#f1f6ff;--muted:#a4b1ca;--line:#303d5c;--lime:#b9ff52;--violet:#bc9aff;--cyan:#6cddff;--yellow:#fff17b;--red:#ff829c;--green:#7ef5bb;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-synthesis:none}*{box-sizing:border-box}html{scrollbar-gutter:stable;overflow-anchor:auto}body{margin:0;background:radial-gradient(ellipse at 8% 2%,#33205c66,transparent 42%),radial-gradient(ellipse at 96% 20%,#124e6c44,transparent 44%),var(--bg);color:var(--text);font-size:15px;line-height:1.5;min-width:0}body:before{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;background-image:linear-gradient(#6a8df108 1px,transparent 1px),linear-gradient(90deg,#6a8df108 1px,transparent 1px);background-size:48px 48px}.terminal{max-width:1540px;margin:auto;padding:28px clamp(14px,3vw,42px) 36px}h1,h2,h3,p{margin:0}h1{font-size:clamp(35px,6vw,70px);letter-spacing:-.055em;line-height:1.08;font-weight:850;text-shadow:0 3px 0 #333b59,0 9px 20px #0009}h1 span{color:var(--lime);text-shadow:0 3px 0 #446825,0 0 26px #b9ff5238}.brand-mark{font-size:.5em;color:var(--violet);margin-left:15px;vertical-align:middle}h2{font-size:clamp(20px,3vw,26px);letter-spacing:-.02em}h3{font-size:20px;line-height:1.35;overflow-wrap:anywhere}.eyebrow{font-size:11px;font-weight:700;letter-spacing:.16em;color:var(--cyan);margin-bottom:12px}.brand-sub{font-size:11px;letter-spacing:.1em;color:var(--muted);margin-top:15px}.masthead{display:flex;justify-content:space-between;gap:22px;align-items:center;margin-bottom:26px}.connection{display:grid;gap:7px;justify-items:end;font-variant-numeric:tabular-nums}.connection strong{font-size:14px}.connection small{font-size:12px;color:var(--muted);overflow-wrap:anywhere}.mode,.tag{display:inline-block;border:1px solid #817237;padding:5px 10px;border-radius:7px;color:var(--yellow);background:#fff17b09;font-size:11px;font-weight:700;letter-spacing:.04em}.tag{border-color:#3e4e72;color:var(--muted);background:#ffffff04;font-size:11px;font-weight:500;letter-spacing:0}.account-panel{background:linear-gradient(125deg,#1b2540,#11182ae6);border:1px solid #6372a6;border-radius:22px;padding:clamp(16px,3vw,26px);box-shadow:inset 0 1px 0 #d0ddff18,0 15px 0 -10px #02040c,0 28px 50px #0005}.section-head{display:flex;justify-content:space-between;align-items:center;gap:14px;margin-bottom:18px}.account-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px}.account-tile{padding:14px;border:1px solid var(--line);border-radius:13px;min-width:0;background:linear-gradient(145deg,#ffffff05,#02061322);box-shadow:inset 0 1px 0 #ffffff07;min-height:95px}.account-tile:first-child{border-color:#6b8a49}.account-tile small{display:block;font-size:10px;font-weight:650;letter-spacing:.055em;color:var(--muted);min-height:30px}.account-tile strong{display:block;font:700 clamp(15px,1.65vw,23px) ui-monospace,SFMono-Regular,Consolas,monospace;font-variant-numeric:tabular-nums;overflow-wrap:anywhere;line-height:1.45}.positive{color:var(--green)!important}.negative{color:var(--red)!important}.neutral{color:var(--text)}.warning{color:var(--yellow)!important}.risk-banner{display:flex;gap:12px;align-items:flex-start;border-left:3px solid var(--yellow);background:#fff17b08;margin-top:18px;padding:10px 12px;min-height:48px;border-radius:0 8px 8px 0;font-size:12px;overflow-wrap:anywhere}.risk-banner b{flex:none;color:var(--yellow);font-size:10px;line-height:1.9}.sub{color:var(--muted);font-size:12px;margin:12px 0 16px;max-width:900px}.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:28px 0 25px;border-bottom:1px solid var(--line);padding-bottom:14px}button,a{touch-action:manipulation}button,.secondary{font-family:inherit;font-size:13px;font-weight:600;cursor:pointer;border:1px solid #485579;border-radius:9px;background:#151e34;color:var(--text);padding:11px 14px;text-decoration:none;line-height:1.4}button:hover,.secondary:hover{border-color:var(--violet);background:#252d4b}button:focus-visible,a:focus-visible{outline:3px solid var(--cyan);outline-offset:4px}.tabs button{min-height:45px;flex:0 1 auto}.tabs button[aria-pressed=true]{color:var(--lime);border-color:#a1d459;background:#b9ff5210;box-shadow:0 0 18px #b9ff520c}.tabs span{margin-left:6px;color:var(--muted);font-variant-numeric:tabular-nums}.card-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:17px;align-items:start}.terminal-card{padding:20px;border:1px solid #445072;border-radius:17px;background:linear-gradient(145deg,#1c2440cc,#10182b);box-shadow:inset 0 1px 0 #ffffff0d,0 10px 0 -7px #050914,0 17px 30px #0004;min-width:0;contain:layout style}.card-heading{display:flex;align-items:flex-start;gap:10px;justify-content:space-between;border-bottom:1px solid #364363;padding-bottom:14px;margin-bottom:14px;min-height:57px}.card-heading h3{color:var(--cyan)}.card-heading small{color:var(--violet);font-size:11px;text-align:right;max-width:60%;overflow-wrap:anywhere}.metric-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px 17px;margin:0}.metric{min-width:0}.metric dt{color:var(--muted);font-size:11px;line-height:1.5;margin-bottom:4px}.metric dd{margin:0;min-height:22px;font:600 13px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}.metric:has([data-field=confirmed]),.metric:has([data-field=forming]),.metric:has([data-field=reason]),.metric:has([data-field=action]){grid-column:1/-1}.metric:has([data-field=confirmed]) dd{color:var(--lime)}.metric:has([data-field=forming]) dd{color:var(--yellow)}.token-card{min-height:785px}.position-card{min-height:400px}.trade-card{min-height:365px}.event-card{min-height:180px}.event-card h3{font-size:14px}.empty{padding:32px 18px;border:1px dashed #4f5e81;border-radius:14px;color:var(--muted);min-height:100px;font-size:14px}.scanner-details{margin-top:20px;border:1px solid var(--line);border-radius:14px;padding:14px;background:#0c1428}.scanner-details summary{cursor:pointer;color:var(--violet);font-size:14px;font-weight:650;min-height:30px}.scanner-details[open] summary{margin-bottom:16px}.scanner-details summary span{color:var(--muted);margin-left:8px}.scanner-details .terminal-card{min-height:0}.section-caption{font-size:14px;color:var(--violet);letter-spacing:.04em;margin:28px 0 17px}.history-links{display:flex;gap:10px;flex-wrap:wrap;margin:24px 0}footer{display:flex;gap:20px;justify-content:space-between;flex-wrap:wrap;margin-top:35px;padding-top:20px;border-top:1px solid var(--line);font-size:12px;color:var(--muted)}footer a{color:var(--cyan)}[hidden]{display:none!important}@media(min-width:1440px){.card-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:1050px){.card-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.account-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:640px){body{font-size:15px}.terminal{padding:20px 12px 28px}.masthead{display:block;margin-bottom:20px}.connection{grid-template-columns:auto 1fr;justify-items:start;align-items:center;margin-top:20px;gap:7px 13px}.connection small{grid-column:1/-1;font-size:12px}.brand-sub{font-size:9px;letter-spacing:.055em}.account-panel{border-radius:17px;padding:15px}.account-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.account-tile{padding:11px;min-height:100px}.account-tile:first-child{grid-column:1/-1;min-height:96px}.account-tile:first-child strong{font-size:30px}.account-tile strong{font-size:15px}.account-tile small{font-size:10px;min-height:31px}.section-head{align-items:flex-start}.section-head .tag{display:none}.section-head .secondary{font-size:11px;padding:9px 10px;max-width:130px;text-align:center;flex:none}.tabs{gap:7px;margin:22px 0}.tabs button{font-size:12px;padding:10px 9px;flex:1 1 42%;min-height:44px}.card-grid{grid-template-columns:minmax(0,1fr);gap:14px}.terminal-card{padding:17px;border-radius:14px}.card-heading h3{font-size:23px}.metric dt{font-size:12px}.metric dd{font-size:14px}.token-card{min-height:850px}.position-card,.trade-card{min-height:0}.risk-banner{display:block;line-height:1.6}.risk-banner b{display:block;margin-bottom:4px}.sub{font-size:12px;line-height:1.65}footer{gap:12px;line-height:1.7}footer span{flex:1 1 100%}}@media(prefers-reduced-motion:reduce){*,*:before,*:after{scroll-behavior:auto!important;animation:none!important;transition:none!important}}
'''


SCRIPT = r'''
(()=>{'use strict';
const $=id=>document.getElementById(id), number=v=>v===null||v===undefined||v===''?null:Number.isFinite(Number(v))?Number(v):null;
const fmt=(v,d=4)=>number(v)===null?'—':number(v).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
const money=v=>number(v)===null?'—':(number(v)>=0?'+':'')+fmt(v)+' USDT';
const pct=v=>number(v)===null?'—':(number(v)>=0?'+':'')+fmt(v,2)+'%';
const side=v=>[1,'1','LONG','long'].includes(v)?'LONG':[-1,'-1','SHORT','short'].includes(v)?'SHORT':'WAIT';
const owns=(value,key)=>Object.prototype.hasOwnProperty.call(value,key);
const priceDigits=v=>number(v)===null||Math.abs(number(v))>=1||number(v)===0?4:Math.min(12,Math.max(6,Math.ceil(-Math.log10(Math.abs(number(v))))+5));
const price=v=>fmt(v,priceDigits(v));
const markStatus=t=>t.mark_fresh===false||number(t.price)===null?(number(t.price_age_seconds)===null?(number(t.price)===null?'WAIT FIRST MARK':'STALE · возраст неизвестен'):'STALE · '+fmt(t.price_age_seconds,1)+' s'):t.mark_fresh===true&&number(t.price_age_seconds)!==null?'FRESH · '+fmt(t.price_age_seconds,1)+' s':'Возраст mark не передан';
const exitState=f=>{const phase=(f.exit_control_state||{}).phase;return ({UNKNOWN:'НЕТ СВЕЖЕГО FLOW',PAUSED:'ПОДТВЕРЖДЕНИЕ ПРИОСТАНОВЛЕНО',OBSERVING:'НАБЛЮДАЕМ КОНТРКОНТРОЛЬ',CONFIRMED:'КОНТРКОНТРОЛЬ ПОДТВЕРЖДЁН',HOLD:'УДЕРЖАНИЕ'})[phase]||phase||'—';};
const tone=v=>number(v)>0?'positive':number(v)<0?'negative':'neutral';
const local=v=>v&&v.pivot_type?v.pivot_type+' · '+price(v.pivot_price):'—';
const executionLocal=v=>local(v)==='—'?'—':local(v)+' · '+(v.confirmation_source||v.interval||'H1');
const scannerQuote=t=>number(t.scanner_price)===null?'—':price(t.scanner_price)+' · '+fmt(t.scanner_price_age_seconds,1)+' s';
const text=(el,value)=>{const t=value===null||value===undefined?'—':String(value);if(el&&el.textContent!==t)el.textContent=t;};
let latest=JSON.parse($('initial-state').textContent), busy=false, activeTab='discovery', lastGood=0;
const fieldCache=new WeakMap();
function metric(label,name,value,kind=''){return {label,name,value,kind};}
function cardView(title,subtitle,metrics,kind=''){return {title,subtitle,metrics,kind};}
function positionData(p){const f=p.features||{},current=p.current_local||f.local_state||{},margin=p.margin_usd??p.margin,pnl=owns(p,'pnl_usdt')?p.pnl_usdt:p.unrealized_pnl;return {originalEntry:p.entry_price??p.original_entry??f.original_entry??p.entry,averageEntry:p.average_entry??p.entry,entryTime:p.entry_time??p.opened,entryLocal:p.entry_local||f.entry_local||f.confirmed_local||f,currentConfirmed:current.confirmed_local||current,currentExecution:current.execution_local||current.confirmed_local||current,currentForming:current.forming_local||(current.pending_pivot_type?{pivot_type:current.pending_pivot_type,pivot_price:current.pending_pivot_price}:{}),pnl,percent:owns(p,'pnl_percent')?p.pnl_percent:number(pnl)!==null&&number(margin)>0?number(pnl)/number(margin)*100:null,margin};}
function decisionText(decision,state){const d=decision&&typeof decision==='object'?(decision.action||decision.status||decision.decision):decision,value=String(d||state||'WAIT').toUpperCase();return ({HOLD:'ПОЗИЦИЯ ОТКРЫТА',ENTRY:'ВХОД',ENTER:'ВХОД',ENTRY_LONG:'ВХОД LONG',ENTER_LONG:'ВХОД LONG',ENTRY_SHORT:'ВХОД SHORT',ENTER_SHORT:'ВХОД SHORT',WAIT:'ЖДЁМ',WAIT_DATA:'ЖДЁМ ДАННЫЕ',WAIT_REENTRY:'ЖДЁМ ПЕРЕЗАХОД',SCANNING:'СКАНИРОВАНИЕ',SELECTED:'ЖДЁМ ПОДТВЕРЖДЕНИЯ',LONG_READY:'ЖДЁМ ВХОД LONG',SHORT_READY:'ЖДЁМ ВХОД SHORT',LONG:'ПОЗИЦИЯ LONG',SHORT:'ПОЗИЦИЯ SHORT'})[value]||value;}
function startupView(p){const s=p.startup||{},stage=String(s.stage||'WAIT_DATA').toUpperCase(),status=String(s.status||'WAITING').toUpperCase(),stages={WAIT_LEASE:'Ожидание PAPER-счёта',WAIT_CONTRACTS:'Загрузка контрактов Bybit',SCANNING_MARKET:'Обзор всего рынка Bybit',ANALYSING_SELECTED:'Анализ выбранной пятёрки',WAITING_ACTIVE_CANDIDATES:'Поиск активных кандидатов',WAIT_SCANNER:'Ожидание свежего обзора',RESTORING:'Восстановление PAPER-состояния',RESTORE:'Восстановление PAPER-состояния',BOOTSTRAP:'Первичный обзор Bybit',METADATA:'Загрузка контрактов Bybit',CONTRACTS:'Загрузка контрактов Bybit',TICKERS:'Обзор всего рынка Bybit',DISCOVERY:'Выбор активной пятёрки',SCANNING:'Обзор всего рынка Bybit',HISTORY:'Подготовка H1 / M15',H1:'Подготовка H1 / M15',FLOW_WARMUP:'Наблюдение исполненных BUY / SELL',WARMING:'Наблюдение исполненных BUY / SELL',ANALYZING:'Анализ пяти выбранных токенов',DECIDING:'Решения: вход или ожидание',READY:'Первичный анализ завершён',RUNNING:'Непрерывный анализ рынка',WAIT_DATA:'Ожидание свежих данных Bybit'},statuses={READY:'ГОТОВО',RUNNING:'РАБОТАЕТ',WAITING:'ЖДЁМ',WARMING:'ПРОГРЕВ ДАННЫХ',PENDING:'ПОДГОТОВКА',FAILED:'НЕТ ДАННЫХ',ERROR:'НЕТ ДАННЫХ',BLOCKED:'ЖДЁМ'};return {stage:stages[stage]||stage,status:statuses[status]||status,reason:s.reason||s.message||'Вход разрешён только после свежей структуры и исполненных сделок.'};}
function tokenView(t){const flow=t.flow_state||{},p=t.position||{},f=p.features||{},risk=f.risk_plan||{},d=positionData(p),held=Object.keys(p).length>0,pnl=held?d.pnl:t.current_pnl_usd,percent=held?d.percent:t.current_pnl_pct;return cardView(t.symbol,'RANK '+(t.rank??'—')+' · '+(t.state||side(t.direction)),[
metric('Цена','price',price(t.price)),metric('Mark / данные','mark_status',markStatus(t)),metric('Scanner quote / возраст','scanner_quote',scannerQuote(t)),metric('Scanner score','score',fmt(t.pandora_win_score)),metric('Исторический confirmed H1','confirmed',local(t.confirmed_local)),metric('Активный local H1/M15','execution',executionLocal(t.execution_local||(t.local_state||{}).execution_local||t.confirmed_local)),metric('Формирующийся local','forming',local(t.forming_local)),metric('Направление','direction',side(t.direction)),metric('Позиция','position',side(p.side)),metric('BUY volume','buy',money(t.buy_volume)),metric('SELL volume','sell',money(t.sell_volume)),metric('Flow imbalance','imbalance',pct(number(t.flow_imbalance)===null?null:number(t.flow_imbalance)*100)),metric('Объём / сек.','velocity',fmt(t.volume_velocity)),metric('Tape','tape',flow.trade_data_fresh?'FRESH':'STALE'),metric('Контроль входа','control',side(flow.sustained_control_side)),metric('Быстрый контроль выхода','fast_control',side(flow.fast_control_side)),metric('Контроль закрытия','exit_control',side(flow.exit_control_side??flow.fast_control_side)),metric('Основание контроля','exit_basis',flow.exit_control_basis),metric('Подтверждение выхода','exit_state',exitState(f)),metric('Причина удержания / выхода','exit_reason',(f.exit_decision||{}).reason),metric('Минутный контекст','context_control',side(flow.context_control_side)),metric('Цена первого входа','original_entry',price(d.originalEntry)),metric('Время входа','entry_time',d.entryTime),metric('Local при входе','entry_local',local(d.entryLocal)),metric('Average entry','entry',price(held?d.averageEntry:t.average_entry)),metric('Маржа','margin',money(t.margin)),metric('Notional','notional',money(t.notional)),metric('Плечо / ADD','leverage',(t.leverage||'—')+'x / '+(t.pyramid_level??0)),metric('Эффективное плечо','effective_leverage',fmt(p.effective_leverage)+'x'),metric('PnL · USDT','pnl',money(pnl),tone(pnl)),metric('PnL / маржа','pnl_pct',pct(percent),tone(percent)),metric('Peak MFE','mfe',money(t.mfe)),metric('MAE','mae',money(t.mae)),metric('MFE giveback','giveback',money(t.mfe_giveback)),metric('Ориентир модели (не SL)','stop',price(risk.stop_price)),metric('Решение','decision',decisionText(t.decision,t.state)),metric('Последнее действие','action',t.last_action),metric('Причина','reason',t.action_reason||(t.decision&&typeof t.decision==='object'?t.decision.reason:null))],'token-card');}
function positionView(p){const f=p.features||{},d=positionData(p),pnl=d.pnl,risk=f.risk_plan||{};return cardView(p.symbol+' · '+side(p.side),d.entryTime,[metric('Цена первого входа','original_entry',price(d.originalEntry)),metric('Время входа','entry_time',d.entryTime),metric('Average entry','entry',price(d.averageEntry)),metric('Mark','mark',price(p.mark)),metric('Local при входе','entry_local',local(d.entryLocal)),metric('Исторический confirmed H1','current_confirmed',local(d.currentConfirmed)),metric('Активный local H1/M15','current_execution',executionLocal(d.currentExecution)),metric('Текущий forming local','current_forming',local(d.currentForming)),metric('PnL · USDT','pnl',money(pnl),tone(pnl)),metric('PnL / маржа','pnl_pct',pct(d.percent),tone(d.percent)),metric('Маржа','margin',money(d.margin)),metric('Notional','notional',money(p.notional_usd??p.notional)),metric('Плечо','leverage',(p.leverage||'—')+'x'),metric('Эффективное плечо','effective_leverage',fmt(p.effective_leverage)+'x'),metric('ADD level','level',f.pyramid_level??0),metric('Peak MFE','mfe',money(f.peak_mfe_usd)),metric('MAE','mae',money(f.mae_usd)),metric('MFE giveback','giveback',money(f.mfe_giveback_usd)),metric('Ориентир модели (не SL)','stop',price(risk.stop_price)),metric('Подтверждение выхода','exit_state',exitState(f)),metric('Причина удержания / выхода','exit_reason',(f.exit_decision||{}).reason)],'position-card');}
function tradeView(t){const f=t.features||{},margin=t.margin??t.margin_usd;return cardView(t.symbol+' · '+side(t.side),t.closed,[metric('Первый вход','original_entry',price(t.entry_price??f.original_entry??f.entry_mark??t.entry)),metric('Время входа','entry_time',t.entry_time??t.opened),metric('Local при входе','entry_local',local(t.entry_local||f)),metric('Средний вход','entry',price(t.entry)),metric('Выход','exit',price(t.exit)),metric('PnL','pnl',money(t.pnl),tone(t.pnl)),metric('PnL / маржа','pnl_pct',pct(number(t.pnl)!==null&&number(margin)>0?number(t.pnl)/number(margin)*100:null),tone(t.pnl)),metric('Маржа','margin',money(margin)),metric('Плечо','leverage',(t.leverage||'—')+'x'),metric('Тип входа','kind',f.entry_kind),metric('Причина выхода','reason',t.reason),metric('Peak MFE','mfe',money(f.peak_mfe_usd)),metric('Giveback','giveback',money(f.mfe_giveback_usd))],'trade-card');}
function makeCard(key,view){const article=document.createElement('article');article.dataset.key=String(key);article.className='terminal-card '+view.kind;const heading=document.createElement('div');heading.className='card-heading';for(const [tag,name] of [['h3','title'],['small','subtitle']]){const parent=document.createElement(tag),span=document.createElement('span');span.dataset.field=name;parent.append(span);heading.append(parent);}article.append(heading);const dl=document.createElement('dl');dl.className='metric-grid';for(const m of view.metrics){const block=document.createElement('div');block.className='metric';const dt=document.createElement('dt');text(dt,m.label);const dd=document.createElement('dd'),span=document.createElement('span');span.dataset.field=m.name;dd.append(span);block.append(dt,dd);dl.append(block);}article.append(dl);return article;}
function fillCard(card,view){let fields=fieldCache.get(card);if(!fields){fields=new Map(Array.from(card.querySelectorAll('[data-field]')).map(node=>[node.dataset.field,node]));fieldCache.set(card,fields);}text(fields.get('title'),view.title);text(fields.get('subtitle'),view.subtitle);for(const m of view.metrics){const element=fields.get(m.name);text(element,m.value);if(element&&element.className!==(m.kind||''))element.className=m.kind||'';}}
function syncList(id,rows,key,view,preserveOrder=false){const box=$(id);if(!box)return;const existing=new Map(Array.from(box.children).map(c=>[c.dataset.key,c])),wanted=new Set();rows.forEach((row,index)=>{const k=String(key(row)),v=view(row);wanted.add(k);let card=existing.get(k);if(!card){card=makeCard(k,v);box.append(card);}fillCard(card,v);if(!preserveOrder&&box.children[index]!==card)box.insertBefore(card,box.children[index]||null);});for(const [k,card]of existing)if(!wanted.has(k))card.remove();$(id+'-empty').hidden=rows.length>0;}
function tokens(data){const p=data.pandora||{};if(p.tokens&&p.tokens.length)return p.tokens;const d=data.discovery||{},details=(p.engine||{}).details||{},selected=new Map((d.selected||[]).map(t=>[t.symbol,t]));return(d.selected_symbols||[]).map(s=>({...selected.get(s),symbol:s,confirmed_local:(details[s]||{}).h1_local||(p.h1_durable||{})[s]||{},flow_state:(details[s]||{}).flow_context||{},state:'SCANNING'}));}
function observedSymbols(data){const p=data.pandora||{},details=(p.engine||{}).details||{},active=[...(p.open_positions||[]).map(row=>row.symbol),...(p.tokens||[]).map(row=>row.symbol),...(data.pandora_symbols||[]),...Object.keys(details)].filter(Boolean);return Array.from(new Set(active.length?active:Object.keys(p.h1_durable||{}))).slice(0,100);}
function anchor(){const nodes=document.querySelectorAll('.tab-panel:not([hidden]) .terminal-card');for(const node of nodes){const rect=node.getBoundingClientRect();if(rect.bottom>0&&rect.top<innerHeight)return {node,top:rect.top};}return null;}
function update(data){const keep=anchor(),p=data.pandora||{},h=data.health||{},account=p.account||{},risk=p.risk||{},valuation=p.margin_valuation||{},start=number(p.starting_equity??500),realized=number(p.realized_pnl),unreal=number(p.unrealized_pnl),total=realized!==null&&unreal!==null?realized+unreal:null,totalPct=total!==null&&start>0?total/start*100:null;
for(const[key,value,valueTone]of [['equity',money(p.total_equity),''],['total-pnl',money(total),tone(total)],['total-pct',pct(totalPct),tone(totalPct)],['start',money(start),''],['realized',money(p.realized_pnl),tone(p.realized_pnl)],['unrealized',money(p.unrealized_pnl),tone(p.unrealized_pnl)],['max-equity',money(p.max_equity),''],['exposure',money(p.current_exposure),''],['free-margin',money(account.free_margin),''],['used-margin',money(account.used_margin),'']]){const node=$('account-'+key);text(node,value);node.className=valueTone;}
text($('readiness'),h.risk_ready?'PAPER ГОТОВ':'НЕ ГОТОВ');$('readiness').className=h.risk_ready?'positive':'warning';text($('risk-reason'),risk.reason||h.engine_error||Object.values(h.execution_errors||{})[0]||(valuation.complete===false?'PORTFOLIO_MARKS_STALE':h.risk_ready?'Fresh market data · PAPER only':'Ожидание актуальных данных / проверки исполнителя'));text($('update-time'),data.snapshot_at||'Время снимка недоступно');const startup=startupView(p);text($('startup-stage'),startup.stage);text($('startup-status'),startup.status);text($('startup-reason'),startup.reason);
const candidates=(data.discovery||{}).top_movers||[];text($('count-candidates'),candidates.length);syncList('candidates',candidates,t=>t.symbol,t=>cardView(t.symbol,'RANK '+(t.rank??'—'),[metric('Score','score',fmt(t.pandora_win_score)),metric('Цена','price',price(t.last)),metric('Текущий импульс %','move',pct(t.scan_return_pct)),metric('Turnover / мин.','turnover',money(t.turnover_per_minute)),metric('BUY USD','buy',money(t.buy_volume)),metric('SELL USD','sell',money(t.sell_volume)),metric('Trades / сек.','trades',fmt(t.trade_velocity)),metric('Executed tape','tape',t.flow_fresh?'FRESH':'WARMING / STALE')]),true);
const details=(p.engine||{}).details||{},durable=p.h1_durable||{},localSymbols=observedSymbols(data);text($('count-locals'),localSymbols.length);syncList('locals',localSymbols,s=>s,s=>{const l=(details[s]||{}).h1_local||durable[s]||{},forming=l.forming_local||(l.pending_pivot_type?{pivot_type:l.pending_pivot_type,pivot_price:l.pending_pivot_price}:{});return cardView(s,side(l.entry_side),[metric('Confirmed local','confirmed',local(l.confirmed_local||l)),metric('Forming local','forming',local(forming)),metric('Разрешение входа','entry_state',l.entry_blocked?'BLOCKED':l.ready?'READY':'WAIT'),metric('Причина','reason',l.entry_block_reason||l.reason||l.confirmation_source)]);},true);
const selected=tokens(data);text($('count-discovery'),selected.length);text($('count-positions'),(p.open_positions||[]).length);syncList('tokens',selected,t=>t.symbol,tokenView,true);syncList('positions',p.open_positions||[],p=>p.symbol+':'+p.opened,positionView,true);syncList('trades',(p.closed_trades||[]).slice(0,30),t=>t.id??(t.symbol+':'+t.opened+':'+t.closed),tradeView);
syncList('adds',p.pyramid_adds||[],a=>a.symbol+':'+a.opened+':'+a.add_number,a=>cardView(a.symbol+' · ADD '+a.add_number,a.timestamp,[metric('Цена','price',price(a.price)),metric('Average entry','average',price(a.average_entry)),metric('Added margin','margin',money(a.added_margin)),metric('Added notional','notional',money(a.added_notional)),metric('MFE до ADD','before',money(a.mfe_before_add)),metric('MFE после ADD','after',money(a.mfe_after_add))]));syncList('events',((p.events||{}).events||[]).slice(0,40),e=>e.id,e=>cardView(e.kind,e.recorded_at,[metric('Токен','symbol',(e.payload||{}).symbol),metric('Причина','reason',(e.payload||{}).reason)],'event-card'));
if(keep&&keep.node.isConnected){const delta=keep.node.getBoundingClientRect().top-keep.top;if(Math.abs(delta)>1)window.scrollBy(0,delta);}latest=data;}
function tab(name){activeTab=name;document.querySelectorAll('[data-tab]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.tab===name)));document.querySelectorAll('.tab-panel').forEach(p=>p.hidden=p.id!=='panel-'+name);try{sessionStorage.setItem('pandora-tab',name);}catch{}}
document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>tab(b.dataset.tab)));try{const saved=sessionStorage.getItem('pandora-tab');if(['discovery','positions','history','audit'].includes(saved))tab(saved);}catch{}
$('sort-rank').addEventListener('click',()=>{const keep=anchor(),box=$('tokens'),ranking=new Map(tokens(latest).map(t=>[String(t.symbol),number(t.rank)??999]));Array.from(box.children).sort((a,b)=>(ranking.get(a.dataset.key)??999)-(ranking.get(b.dataset.key)??999)).forEach(node=>box.append(node));if(keep&&keep.node.isConnected)window.scrollBy(0,keep.node.getBoundingClientRect().top-keep.top);});
async function poll(){if(busy||document.hidden)return;busy=true;const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),8000);try{const response=await fetch('/api/pandora',{cache:'no-store',signal:controller.signal,headers:{Accept:'application/json'}});if(!response.ok)throw Error('HTTP '+response.status);const data=await response.json();if(!data||!data.pandora||!data.health)throw Error('Неверный формат API');update(data);lastGood=Date.now();const published=Date.parse(data.snapshot_at),age=Number.isFinite(published)?Math.max(0,(lastGood-published)/1000):null;if(age!==null&&age>15){text($('connection-state'),'API снимок устарел · '+fmt(age,1)+' s');$('connection-state').className='negative';text($('readiness'),'НЕТ СВЕЖЕГО API');$('readiness').className='negative';}else{text($('connection-state'),'JSON подключён · '+new Date(lastGood).toLocaleTimeString());$('connection-state').className='positive';}}catch(error){text($('connection-state'),'Нет обновления · '+String(error.message)+' · показан последний снимок');$('connection-state').className='negative';text($('readiness'),'НЕТ СВЕЖЕГО API');$('readiness').className='negative';}finally{clearTimeout(timeout);busy=false;}}
document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll();});setInterval(poll,1000);poll();
})();
'''
