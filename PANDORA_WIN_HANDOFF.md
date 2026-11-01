# Pandora Win — передача разработчику

## Границы приложения

В приложении один движок Pandora Win, один PAPER-счёт и один монитор. Реальные ордера и приватные exchange API отсутствуют. Рабочее пространство PostgreSQL — только `pandora_win_*`.

При первом создании этого пространства: equity 500 USDT, realized PnL 0, нет позиций, сделок, ADDs и накопленного журнала. Повторный запуск сохраняет собственное состояние приложения. Не добавляйте очистку на каждый restart. Данные других пространств таблиц не читаются и не объединяются с этим счётом; их физическое удаление не происходит штатным запуском.

## Поток исполнения

1. Восстановить PostgreSQL-состояние и получить single-writer lease.
2. Одновременно загрузить contract metadata и market tickers, подключить public WebSocket.
3. Непрерывно выбирать до пяти текущих активных рынков и прогревать кандидатный executed tape.
4. Приоритетно получить H1/M15 для выбранных/удерживаемых токенов через `HistoryBootstrap`.
5. Проверить online confirmed/forming locals, свежесть собственного mark и реальный BUY/SELL control.
6. Открыть PAPER-позицию либо показать конкретное WAIT. При открытой позиции управлять удержанием, структурным выходом, ADD и последующим re-entry/reversal.

Первичный обзор не имеет искусственного таймера, но вход не должен опережать свежие market data и 15s фактически наблюдавшегося tape. Socket uptime не заменяет trade evidence.

## Инварианты денег и данных

- Деньги, открытие/закрытие и ADD меняются атомарно под lease/fence. Повторное закрытие не начисляет PnL повторно.
- ACCOUNT_LOCK сериализует управление и ручное PAPER-close. Перед публикацией позиции проверяются `opened` и результат canonical UPDATE.
- При stale mark одной позиции нельзя финансировать новый риск её устаревшей прибылью. Свежая собственная цена всё ещё используется для честной оценки maintenance.
- Минимум входа — 10% текущего equity по марже и 10x; выбранная маржа/плечо зависят от actual flow/price response/local и funding/contract/model geometry.
- Compounding пересчитывает размер после net PnL. Ни смена плеча, ни ADD не создают equity.
- Average entry — quantity weighted. Ранее внесённый collateral не высвобождается как доход.
- Фиксированных процентных SL/TP, MFE-giveback выходов и PnL-пауз нет. Основной выход определяется выполненным control transfer и причинной структурой цены. Модельный maintenance breach может дать убыток и не скрывается.
- После ротации открытая позиция продолжает получать данные. Удаление токена из Discovery не удаляет его ledger и не означает фиктивное закрытие.

## Состояние и persistence

Сохраняются account equity/realized PnL, позиции и average entry, отдельные ADDs, MFE/MAE, confirmed/forming locals, scanner selection, watch/re-entry и причины действий. Checkpoints позиции — примерно 1s, scanner/account/повторяющихся состояний — примерно 5s. Последние незаписанные наблюдения могут потеряться при аварии; money/close/ADD защищены транзакцией.

Состояния токена включают SELECTED, FORMING_LOCAL_LOW/HIGH, LONG/SHORT_READY, LONG/SHORT, LONG/SHORT_PYRAMID, LONG/SHORT_WEAKENING, WAIT_REENTRY, FADING и ROTATE_OUT. Журнал фиксирует market context открытия, удержания, доливки, закрытия, re-entry, reversal и ротации.

Глобальный outage сохраняет selection/watch и блокирует неподтверждённый вход. Один quiet/stale токен не замораживает всю пятёрку. Fast control 5/15s для структурного закрытия отделён от minute context нового входа; старый минутный объём не должен задерживать подтверждённый контрконтроль.

Защита от выхода на слабом откате: `MIN_CONTROL_IMBALANCE=0.20` (60/40 executed volume) в обоих быстрых окнах плюс price response. Entry также требует этого минутного перевеса. Exit проходит через единый `pressure_exit`, включая противоположный H1 local: минимум 3 секунды противоположного control по свежим exchange events и структурное подтверждение. `features.exit_control_state` сохраняет наблюдение; повторный polling не добавляет времени. Neutral/own/stale, gap >5s и благоприятный экстремум сбрасывают наблюдение. Не обходите этот gate прямым close по одному fast-control tick. Контракты покрывает `tests/test_control_hysteresis.py`, а wire-тесты проверяют HOLD первой контратаки и последующий подтверждённый выход. Дополнительное подтверждение может отложить выход; оно не гарантирует сохранение всей MFE.

## Интерфейс

`pandora_monitor.py` содержит мобильный монитор с keyed JSON-обновлениями. Источник — `/api/pandora`, корневой объект `pandora`. Для позиции различаются:

- `entry_price`, `entry_time`, `entry_local` — фактический первый вход;
- `average_entry` — средний entry после ADD;
- `current_local` — актуальные confirmed/forming locals;
- `pnl_usdt`, `pnl_percent` — net PnL и процент от маржи;
- leverage/эффективная экспозиция, MFE/MAE и список ADDs.

`pandora.startup` показывает стадию первичного анализа и данные выбранных пяти. `token.decision` содержит action, reason, message и data_ready. Read-only сигнал готовности не заменяет committed OPEN.

Сделки: `/api/pandora/history` и `/pandora/history`. Журнал: `/api/pandora/events`. Read-only schema: `/openapi.json`. `/health` не доказывает market readiness; `/health/risk` требует актуальных данных и работающего executor.

## Запуск и проверка

Запуск: Python 3.12, зависимости `requirements.txt`, безопасно заданный `DATABASE_URL`, затем `python app.py`. Dockerfile использует тот же entrypoint. Нужен доступ к `api.bybit.com` и `stream.bybit.com`. Public market data не требует торгового ключа.

Команда проверки: `python scripts/run_release_tests.py --report validation/release-result.json` с отдельной тестовой PostgreSQL и binding-файлом `PANDORA_TEST_DATABASE_URL_FILE`. Тесты — software contracts и синтетический WebSocket, не доказательство доходности. Названия основных модулей и параметры перечислены в README_PANDORA_WIN.md.

Live Bybit, состояние рабочей базы и deploy Render требуют проверки доступом к соответствующей среде. Нельзя объявлять их подтверждёнными по локальному HTTP или тестовому PnL. Не обещать 100% win rate, прибыльный fill или отсутствие ликвидаций: maintenance — приближённая модель без точных биржевых tiers/funding/slippage.

Полный ZIP должен включать runtime, Dockerfile, зависимости, монитор, тесты, эти документы и manifest. Credentials, database dumps, venv и caches исключаются.
