# PANDORA Flow v2 — передача разработчику

Experiment `pandora_flow_v2`, PAPER only, ветка `pandora-flow-v2`. Реальных ордеров нет. Render deploy требует отдельной команды пользователя. Полная архитектура и команды: [README_PANDORA_WIN.md](README_PANDORA_WIN.md).

## Стратегия и money engine

Только новый принятый Public Trade с независимым ID/sequence создаёт directional evidence. `FlowStrategy.ingest` обновляет control/FSM; `evaluate` не накапливает proofs. Polling, свечи и minute/hour buckets не подтверждают entry/exit/re-entry/reversal. Freshness может запретить риск, но не подменяет control.

`FlowStrategy._analysis` переводит flow в старый risk API: alignment flags, observed executed-price reference и learned noise. Не подключайте H1/M15/cached candle analysis к этому adapter. `pandora_risk.py` и `accounting.py` сохранены; audit проверяет baseline hashes.

Control: imbalance ≥0.20 по модулю, независимые executions, causal response, отсутствие absorption. Named `FlowConfig.min_control_events=3` заменяет ожидание секунд. Measurement/retention именованы в том же config; completed-window gates отсутствуют. Hysteresis требует takeover за learned noise и round-trip costs. Post-close evidence начинается после actual commit; тот же trade не разворачивает позицию. Re-entry не ограничен искусственным count.

Flow regimes: BUY_CONTROL / BUY_WEAKENING / NEUTRAL / SELL_WEAKENING / SELL_CONTROL. Position FSM: FLAT / LONG / LONG_EXIT_CONFIRMING / FLAT_AFTER_LONG / SHORT / SHORT_EXIT_CONFIRMING / FLAT_AFTER_SHORT. `on_open`/`on_close` подтверждают фактическую денежную операцию. MFE/MAE/giveback — аналитика, не fixed TP/SL.

## Universe и восстановление

LiveScanner видит весь linear USDT perpetual universe. HourlyUniverse фиксирует ranking на refresh: первый сразу, далее UTC hour boundary. Entry set внутри часа неизменен; ranking не выбирает направление.

PostgreSQL checkpoint сохраняет selection metadata, last/next refresh и managed symbols. Restart восстанавливает schedule; пропущенные часы дают один refresh. Position вне новой пятёрки становится MANAGED_POSITION и продолжает subscriptions/mark/FSM/exit/MFE/MAE. Ротация не закрывает позицию; после закрытия вне пятёрки новых entries нет.

FSM сохраняет bounded causal history, sequence cursor, confirmations, pressure/noise, close acknowledgement и re-entry state. Collector восстанавливает sequence floor, чтобы replay не стал новым evidence. Проверяйте universe/FSM вместе с account/позициями и MFE/MAE.

## Account и controlled initialization

Соединения ограничены схемой pandora_flow_v2 без public fallback. Старые public.pandora_win_* — архив; не объединять с новым history/PnL. Registry marker исключает reset на restart.

После кода и тестов запустить `python scripts/reset_paper_experiment.py` с целевым DATABASE_URL из окружения. Первая транзакция создаёт чистый account 500 USDT, PnL 0 и пустые позиции/trades/watch/FSM/ADDs. Активный lease, непустое unregistered состояние, mismatch registry и параллельный initializer дают отказ без удаления данных. Повторная команда возвращает сохранённое состояние. Приложение без initialized marker отказывается стартовать.

Ни startup, ни restart, ни hourly refresh не обнуляют account. Подтверждать reset нужно JSON команды и monitor того же namespace. Тестовый namespace не доказывает reset production.

## Data uncertainty и invariants

Stale/invalid tape → DATA_UNCERTAIN; entry/reversal запрещены. Poll/reconnect не делают старый flow свежим. Staleness сама не вызывает CLOSE. Loss-of-tape protection требует свежего независимого mark за прежней causal boundary дальше noise/cost allowance; она не открывает противоположную сторону. Maintenance guard остаётся отдельной денежной защитой.

OPEN/CLOSE/ADD используют account lock, lease/fence и transactional ledger. Повторный close не начисляет PnL дважды. Unknown stale PnL не финансирует новый риск. Average entry quantity weighted; collateral не является прибылью. Dynamic margin/leverage, costs, maintenance, account constraints и compounding сохранены.

## Monitor, logging и verification

Monitor/API показывают experiment ID/account, hourly TOP-5/metadata, MANAGED_POSITION, control/absorption/freshness, actual position/FSM, decision/reason. Meaningful journal включает exchange/receive times, before/after, price/mark/entry, flow, PnL/MFE/MAE и причину. Recommendation не равна committed OPEN.

Команды: `python scripts/audit_flow_decision_path.py --report validation/flow-decision-path.json` и `python scripts/run_release_tests.py --report validation/release-result.json`. Runner использует отдельную PostgreSQL и matching PANDORA_TEST_DATABASE_URL_FILE.

`python scripts/run_flow_acceptance.py --report validation/flow-acceptance.json` выдаёт отдельный PASS/FAIL/ERROR/SKIP/NOT_RUN для каждого acceptance 1–16. Shared scenarios выполняются один раз; skip/missing test не считается PASS. В отчёт входят actual PostgreSQL/loopback WebSocket execution/restart/reversal contracts.

Audit обходит explicit active roots и reviewed project dependencies; legacy UI/history не сканируются как trading code. Mutation tests должны отклонять M15 helper, calendar bucket, cached candle state и неаудированный directional helper. Не расширяйте allowlist ради зелёного отчёта без чтения добавленной функции. Baseline и acceptance matrix: [PANDORA_FLOW_V2_AUDIT.md](PANDORA_FLOW_V2_AUDIT.md).

Source ZIP собирается scripts/package_source.py; credentials, dumps, venv, caches и Git metadata исключаются. Итоговый отчёт отдельно называет suite/acceptance 1–16, reset environment, monitor verification и deployment status. Software tests не доказывают доходность или live exchange readiness.
