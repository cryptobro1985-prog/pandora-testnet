"""Read-only executed-flow readiness; OPEN means a committed position only.

The legacy analysis and h1_verified arguments remain accepted for callers. Neither
historical structure nor candle confirmation participates in this status path.
"""


def entry_status(symbol, analysis, flow, position=None, watch=None, *,
                 active=False, scanner_ready=False, instrument_ready=False,
                 h1_verified=False, mark=None, checkpoint_ready=False,
                 rejection=None, stamp=0, flow_decision=None):
    flow = flow or {}
    decision = flow_decision or flow.get('last_decision') or {}
    messages={
        'POSITION_ALREADY_OPEN':'Позиция открыта; управление по свежему executed BUY / SELL flow.',
        'DATA_UNCERTAIN':'Поток сделок устарел или последовательность не подтверждена. Входы запрещены; позиция ждёт восстановления данных.',
        'WAIT_ENGINE_LEASE':'Ожидаем право управления PAPER-счётом.',
        'WAIT_CONTRACT_METADATA':'Загружаем параметры контракта Bybit.',
        'WAIT_SCANNER_OBSERVATIONS':'Ожидаем сохранённый hourly TOP-5.',
        'WAIT_FRESH_MARK':'Ожидаем свежую цену токена.',
        'WAIT_PUBLIC_TRADES':'Ожидаем свежие исполненные покупки и продажи.',
        'WAIT_OBSERVED_TAPE':'Наблюдаем независимые BUY / SELL executions; контроль ещё не подтверждён.',
        'WAIT_DATABASE_CHECKPOINT':'Подтверждаем актуальное состояние PAPER-счёта.',
        'WAIT_REENTRY_CONTROL':'Ожидаем новый независимый executed control для перезахода.',
        'WAIT_BUY_CONTROL':'LONG не открываем: устойчивый BUY control и price response не подтверждены.',
        'WAIT_SELL_CONTROL':'SHORT не открываем: устойчивый SELL control и price response не подтверждены.',
        'WAIT_FLOW_CONTROL':'Ожидаем устойчивый BUY или SELL control с price response без absorption.',
        'ENTRY_SIGNAL_READY_WAITING_EXECUTOR':'Executed flow подтверждён; ожидаем запись исполнителя.',
        'MIN_ENTRY_MARGIN_UNFUNDED':'Свободной маржи недостаточно для минимального входа.',
        'CONTRACT_OR_GEOMETRY_BELOW_MIN_LEVERAGE':'Сейчас нельзя обеспечить вход с минимальным плечом 10x.',
    }
    fresh=bool(flow.get('trade_data_fresh') and flow.get('sequence_valid', True))
    ready=bool(active and scanner_ready and instrument_ready and mark is not None and
               checkpoint_ready and fresh and flow.get('evidence_ready'))
    def result(reason, phase='WAIT', **extra):
        return dict(action=phase, reason=reason, message=messages.get(reason, reason),
                    data_ready=ready, **extra)
    if position:
        if not fresh or decision.get('action')=='DATA_UNCERTAIN':
            return result('DATA_UNCERTAIN', 'DATA_UNCERTAIN', side=position.get('side'))
        out=result('POSITION_ALREADY_OPEN', 'HOLD', side=position.get('side'))
        if decision.get('reason'):
            out.update(reason=decision['reason'], message=decision['reason'],
                       flow_action=decision.get('action'))
        return out
    if not active:return result('WAIT_ENGINE_LEASE')
    if not instrument_ready:return result('WAIT_CONTRACT_METADATA')
    if not scanner_ready:return result('WAIT_SCANNER_OBSERVATIONS')
    if mark is None:return result('WAIT_FRESH_MARK')
    if not fresh:return result('WAIT_PUBLIC_TRADES')
    if not flow.get('evidence_ready'):
        # Compatibility telemetry only: elapsed observation never confirms control.
        required=float(flow.get('evidence_required_seconds') or 0)
        coverage=float(flow.get('trade_coverage_seconds') or 0)
        return result('WAIT_OBSERVED_TAPE', observed_seconds=coverage,
                      required_seconds=required, remaining_observation_seconds=max(0.,required-coverage))
    if not checkpoint_ready:return result('WAIT_DATABASE_CHECKPOINT')
    if decision:
        side=int(decision.get('side') or 0)
        if decision.get('action') not in ('OPEN', 'REENTRY'):
            out=result('WAIT_REENTRY_CONTROL' if watch else 'WAIT_FLOW_CONTROL', side=side)
            if decision.get('reason'):out.update(reason=decision['reason'], message=decision['reason'])
            return out
    else:
        side=int(flow.get('sustained_control_side') or 0)
        if side not in (-1, 1):
            fast=int(flow.get('fast_control_side') or 0)
            return result('WAIT_BUY_CONTROL' if fast<0 else 'WAIT_SELL_CONTROL' if fast>0 else 'WAIT_FLOW_CONTROL', side=side)
        if watch:return result('WAIT_REENTRY_CONTROL', side=side)
    if rejection:return result(rejection, signal_ready=True, side=side)
    # Readiness never reports an order that the paper engine has not committed.
    out=result('ENTRY_SIGNAL_READY_WAITING_EXECUTOR', signal_ready=True, side=side)
    if decision.get('reason'):out['flow_reason']=decision['reason']
    return out


def startup_snapshot(state, tokens, *, observed_markets=0, history=None):
    universe=len(state.get('_bybit_instruments') or {})
    active_tokens=[t for t in tokens if t.get('management_state')!='MANAGED_POSITION']
    selected=len(active_tokens)
    decision_ready=sum(bool(t.get('decision',{}).get('data_ready')) for t in active_tokens)
    opened=sum(bool(t.get('position')) or t.get('decision',{}).get('action')=='HOLD' for t in tokens)
    if not state.get('engine_active'):stage='WAIT_LEASE'
    elif not universe:stage='WAIT_CONTRACTS'
    elif not selected:stage='SCANNING_MARKET'
    elif (state.get('bybit_discovery') or {}).get('selection_frozen'):stage='WAIT_SCANNER'
    elif decision_ready<selected:stage='ANALYSING_SELECTED'
    elif selected<5:stage='WAITING_ACTIVE_CANDIDATES'
    else:stage='RUNNING'
    reasons={t.get('symbol'):t.get('decision',{}).get('reason') for t in tokens}
    return dict(stage=stage,status='READY' if stage=='RUNNING' else 'WAITING',
                reason=f'Контрактов: {universe}; рынков в обзоре: {observed_markets}; TOP-5: {selected}/5; со свежим executed flow: {decision_ready}/{selected}.',
                target_tokens=5,selected_tokens=selected,decisions_ready=decision_ready,
                opened_positions=opened,waiting_tokens=max(0,selected-sum(bool(t.get('position')) for t in active_tokens)),
                universe_markets=universe,observed_markets=observed_markets,
                token_reasons=reasons,history=history or {},
                note='Executed flow determines direction. Hourly TOP-5 refresh changes the entry universe only.')
