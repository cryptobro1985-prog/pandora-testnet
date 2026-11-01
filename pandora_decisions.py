"""Read-only live startup/entry status; OPEN means a committed position only."""
from local_order_flow import initial_entry_candidate, reentry_ready


def entry_status(symbol, analysis, flow, position=None, watch=None, *,
                 active=False, scanner_ready=False, instrument_ready=False,
                 h1_verified=False, mark=None, checkpoint_ready=False,
                 rejection=None, stamp=0):
    messages={
        'POSITION_ALREADY_OPEN':'Позиция открыта; продолжаем управление по рынку.',
        'WAIT_ENGINE_LEASE':'Ожидаем право управления PAPER-счётом.',
        'WAIT_CONTRACT_METADATA':'Загружаем параметры контракта Bybit.',
        'WAIT_SCANNER_OBSERVATIONS':'Ожидаем актуальный обзор рынка.',
        'WAIT_LOCAL_STRUCTURE':'Загружаем и подтверждаем структуру локалов H1 / M15.',
        'WAIT_FRESH_LOCAL':'Ожидаем свежую структуру локала.',
        'WAIT_FRESH_MARK':'Ожидаем свежую цену токена.',
        'WAIT_PUBLIC_TRADES':'Ожидаем свежие исполненные покупки и продажи.',
        'WAIT_OBSERVED_TAPE':'Наблюдаем реальный поток BUY / SELL; статистика ещё не готова.',
        'WAIT_DATABASE_CHECKPOINT':'Подтверждаем актуальное состояние PAPER-счёта.',
        'WAIT_REENTRY_CONTROL':'Ожидаем подтверждённое возвращение контроля для перезахода.',
        'WAIT_BUY_CONTROL':'LONG не открываем: текущая сила покупателей не подтверждена.',
        'WAIT_SELL_CONTROL':'SHORT не открываем: текущая сила продавцов не подтверждена.',
        'ENTRY_SIGNAL_READY_WAITING_EXECUTOR':'Условия входа подтверждены; ожидаем запись исполнителя.',
        'MIN_ENTRY_MARGIN_UNFUNDED':'Свободной маржи недостаточно для минимального входа.',
        'CONTRACT_OR_GEOMETRY_BELOW_MIN_LEVERAGE':'Сейчас нельзя обеспечить вход с минимальным плечом10x.',
    }
    def result(reason, phase='WAIT', **extra):
        ready=bool(active and scanner_ready and instrument_ready and h1_verified and mark is not None and checkpoint_ready and flow.get('trade_data_fresh') and flow.get('evidence_ready') and analysis.get('live_structure_fresh',True))
        return dict(action=phase,reason=reason,message=messages.get(reason,reason),data_ready=ready,**extra)
    if position:
        return result('POSITION_ALREADY_OPEN','HOLD',side=position.get('side'))
    if not active:return result('WAIT_ENGINE_LEASE')
    if not instrument_ready:return result('WAIT_CONTRACT_METADATA')
    if not scanner_ready:return result('WAIT_SCANNER_OBSERVATIONS')
    if not analysis or not h1_verified or not analysis.get('anchor_confirmed'):
        return result('WAIT_LOCAL_STRUCTURE')
    if analysis.get('entry_blocked') or analysis.get('live_structure_fresh') is False:
        return result(analysis.get('entry_block_reason') or 'WAIT_FRESH_LOCAL')
    if mark is None:return result('WAIT_FRESH_MARK')
    if not flow.get('trade_data_fresh'):return result('WAIT_PUBLIC_TRADES')
    required=float(flow.get('evidence_required_seconds',15))
    coverage=float(flow.get('trade_coverage_seconds') or 0)
    if not flow.get('evidence_ready'):
        return result('WAIT_OBSERVED_TAPE',observed_seconds=coverage,
                      required_seconds=required,remaining_observation_seconds=max(0.,required-coverage))
    if not checkpoint_ready:return result('WAIT_DATABASE_CHECKPOINT')
    side=int(analysis.get('entry_side') or 0)
    if watch and int(watch.get('side') or 0)==side:
        if not reentry_ready(side,None,mark,watch,flow,stamp):return result('WAIT_REENTRY_CONTROL',side=side)
    elif not initial_entry_candidate(symbol,analysis,None,flow,stamp).get('eligible'):
        return result('WAIT_BUY_CONTROL' if side>0 else 'WAIT_SELL_CONTROL',side=side)
    if rejection:return result(rejection,signal_ready=True,side=side)
    # A read-only monitor must never report an order that has not committed.
    return result('ENTRY_SIGNAL_READY_WAITING_EXECUTOR',signal_ready=True,side=side)


def startup_snapshot(state, tokens, *, observed_markets=0, history=None):
    universe=len(state.get('_bybit_instruments') or {})
    selected=len(tokens)
    decision_ready=sum(bool(t.get('decision',{}).get('data_ready')) for t in tokens)
    opened=sum(t.get('decision',{}).get('action')=='HOLD' for t in tokens)
    if not state.get('engine_active'):stage='WAIT_LEASE'
    elif not universe:stage='WAIT_CONTRACTS'
    elif not selected:stage='SCANNING_MARKET'
    elif (state.get('bybit_discovery') or {}).get('selection_frozen'):stage='WAIT_SCANNER'
    elif decision_ready<selected:stage='ANALYSING_SELECTED'
    elif selected<5:stage='WAITING_ACTIVE_CANDIDATES'
    else:stage='RUNNING'
    reasons={t.get('symbol'):t.get('decision',{}).get('reason') for t in tokens}
    return dict(stage=stage,status='READY' if stage=='RUNNING' else 'WAITING',
                reason=f'Контрактов: {universe}; рынков в обзоре: {observed_markets}; выбрано: {selected}/5; с актуальными данными: {decision_ready}/{selected}.',
                target_tokens=5,selected_tokens=selected,decisions_ready=decision_ready,
                opened_positions=opened,waiting_tokens=selected-opened,
                universe_markets=universe,observed_markets=observed_markets,
                token_reasons=reasons,history=history or {},
                note='Observation starts immediately; live entry requires actual fresh tape and verified structure.')
