# Pandora Win — handoff, 2026-11-01

Актуальное дополнение после глубокого аудита: DEEP_AUDIT.md. Risk policy заменил фиксированное плечо25x адаптивным диапазоном10–50x и маржой10–30%; фиксированных loss caps/PnL-пауз и процентных SL/TP/MFE-exit по итоговому требованию нет. Старые описания базовой версии ниже относятся к исходному snapshot; текущий код и DEEP_AUDIT имеют приоритет.

## Происхождение

Изучен и безопасно распакован пользовательский `Pandora_Win_latest_strategy_2026-11-01.zip` (8 854 байта, SHA-256 `47e6f5dad8da8694283adddabf5beb13bf1f7e57e4d9337c007e58ae28851769`). В нём восемь файлов и ссылка на исходный коммит `c023c653ad8f07205817211ba8557faf261751bf`. Это компактная выжимка стратегии, в которой отсутствуют рабочие PostgreSQL/HTTP/WS supervision и монитор. Полная версия собрана на базе этого кода и полного одноимённого GitHub-репозитория того же коммита. Полный промпт пользователя учтён; реальные ордера выключены.

## Реализация

Market-wide streaming scanner получает тикеры разрешённых USDT perpetual, поддерживает ограниченный кандидатный trade pool и динамический Top-5. Public Trades/kline-подписки включают выбранные, кандидатов и сохранённые позиции/watch; исключённая позиция не теряет управление. Восстановление REST используется при отсутствии нужных свежих данных, а не для основного быстрого цикла.

Существующий candle normalizer, transport dedup/staleness, PostgreSQL lease/fence, accounting и канонические ledgers сохранены. Незакрытая свеча теперь имеет метку реального наблюдения. Confirmed H1 хранится отдельно от forming; входы от пробитого старого экстремума блокируются. M15 подтверждает наблюдавшийся экстремум только закрытой структурой, которая следует после его наблюдения, вместе с sustained executed control.

Executed-flow вычисляет фактический USD notional и quantity по окнам 5/15/30/60/180/300 секунд. Состояния цены/давления сохраняют поглощённые откаты и ретесты. Удержание не привязано к фиксированному MFE target. После структурного выхода сохраняется зеркальный watch; смена подтверждённой структуры плюс opposite control разрешает reverse.

Доливки реализованы в `pandora_win_core.py` и атомарно применяются `PandoraRuntime.pyramid`. Новая цена/объём должны усиливать прибыльную существующую позицию. Unique key `(symbol, opened, add_number)` предотвращает повторную доливку при повторной обработке. `entry`, `notional`, `margin`, features и отдельная ADD-запись обновляются одной fenced-транзакцией. Quantity-weighted average entry обеспечивает равенство PnL сумме отдельных legs. Realized equity при ADD не меняется; комиссии всех legs входят в net PnL при mark/close.

MFE/MAE USD, peak, giveback, mark, PnL, flow/local state и список adds содержатся в position features и сохраняются в PostgreSQL. Доливки также доступны из отдельной таблицы после закрытия позиции. Semantic OPEN/ADD/CLOSE/REENTRY/REVERSE и их market context пишутся в audit; повторяющиеся HOLD/WAIT ограничены по частоте. Scanner selection/state и account max equity имеют отдельные checkpoints.

## Persistence и важные инварианты

- `local_v12_account_state`, `local_v12_positions`, `local_v12_trade_history`, `local_v12_watchlist`, `local_h1_direction`, `local_candle_checkpoints` и `audit_journal` остаются каноническими.
- `pandora_token_state` хранит состояние/действие/причину и last closed side для определения reversal после рестарта.
- `pandora_runtime_state` хранит scanner и max equity/exposure checkpoint.
- `pandora_pyramid_adds` хранит каждую доливку отдельно.
- Startup создаёт отсутствующие таблицы/счета, не стирая существующую историю и balance. Исторические автоматические TRUNCATE/reset удалены из всех четырёх книг.
- Single writer lease обязателен; standby перечитывает состояние после получения lease и сбрасывает process-local H1 proof. Старый снимок не доказывает свежесть market data.
- Закрытие начисляет PnL только если каноническая позиция действительно удалена в этой транзакции. Повторное закрытие не начисляет деньги.
- Selected markets и уже открытые позиции — разные множества. ROTATE_OUT не закрывает позицию административно и не удаляет её ledger.
- Базовая маржа 20% текущего equity, плечо не выше 25 и contract maximum, fee reserve учитывается перед выделением средств.
- Сравнительные движки сохранены, но их торговля по умолчанию выключена. Их балансы не суммируются с Pandora Win.

## State/API

`/api/pandora` и `/api/dashboard` содержат `strategy1_primary`: account totals, max equity, exposure, selected token rows с полным flow/local/position context, open/closed trades, all recent durable pyramid adds, re-entries/reversals/rotations и runtime state. Монитор показывает эти данные и журнал, отдельные результаты счетов и ссылки на полную историю. `/api/strategy1/events` и `/api/strategy1/history` поддерживают `before`, `limit` и безопасные bind parameters. Missing aggregates отображаются как недоступные, без подстановки нулевой прибыли.

## Явные решения и пределы

Lookback локалов — четыре закрытых H1, подтверждение — последующая закрытая структура. M15 не угадывает будущий high/low, его данные должны следовать после наблюдения экстремума. Sustained control — согласованная сторона USD-volume и price response в наблюдаемых быстрых/минутном окнах; количество сделок используется для описания активности, а не как вес силы.

Scanner score — равновесные percentile ranks описанных в README признаков. Для совсем нового ticker bootstrap допускает положительный 24h change, пока не накопились текущие samples; после этого важна текущая положительная динамика. Executed trades прогреваются для 30 кандидатов по умолчанию, не для каждого listed-контракта одновременно. Эти решения — открытые алгоритмические определения неоднозначных пунктов ТЗ, без оптимизации и обещаний доходности.

Pyramiding risk caps по умолчанию: 2 adds, до 10% equity на add, суммарно до 40% equity на одну позицию. Доступные ограничения проверяются повторно при ADD. Неполные окна явно обозначены; volume не экстраполируется. Checkpoints позиции — примерно 1s, scanner/account и повторяющиеся состояния — примерно 5s; как при любом checkpoint, аварийное завершение может потерять последние незаписанные наблюдения. Атомарные money/ADD/close события не зависят от этого интервала.

Резкий V-разворот без поглощённого отката/ретеста может дать поздний структурный выход; MFE — измерение наблюдавшейся возможности, а не гарантия фиксации максимальной цены. Funding, реальное проскальзывание и биржевые liquidation costs не моделируются. Не добавлены MACD, EMA, RSI, MFI, Bollinger или другие классические индикаторы.

## Проверка и передача

Набор `scripts/run_release_tests.py` выполняет синтетические software contracts, локальный WebSocket и PostgreSQL. Проверяются исходные регрессии, causal prefixes, stale transport, volume-vs-count/absorption, scanner rotation, forming/confirmed/M15 chronology, quantity accounting, pyramiding cap/idempotency/restart, compounding и runtime LONG→close→SHORT без дублирующего reversal. Результат окончательного запуска находится в `validation/release-result.json`, подробности — в `validation/release.log`. Это не бэктест и не историческая доходность.

Фактический HTTP-запуск полной версии на отдельной локальной PostgreSQL проверен: `/health`, `/api/pandora`, `/api/dashboard`, history/events и `/` отвечают 200. Без живого потока `risk_ready=false`, PAPER_ONLY сохраняется.

Живой Bybit и Render в этой сессии не подтверждены: proxy CONNECT отклонён с 403, а выбранное пользователем приложение Render не предоставило инструментов. Production database, deploy status и длительная рыночная работа не проверялись. Эти внешние ограничения не заменены искусственными успешными live-результатами. Дальнейшая проверка поведения/настройка стратегии — отдельный этап пользователя.

`PANDORA_WIN_COMPLETE.zip` содержит все исходники, runtime, зависимости, Dockerfile, тесты, CI, эти документы, текущие отчёты и manifest с per-file SHA-256. Credentials, databases, venv, кэши и Git metadata исключены. Запуск и все основные параметры перечислены в README_PANDORA_WIN.md.

## Дополнение: старт и provenance позиций

Выбранные пять больше не ждут последовательного обхода base/candidate history. HistoryBootstrap:5 приоритетных workers +1 background, shared5req/s, bounded futures, приоритет выбранных/сохранённых токенов каждые0.2с, per-symbol backoff. Supervisor запускает его сразу, HTTP доступен во время подготовки. needs_local_history проверяет актуальность/непрерывность H1/M15. Пустая/неполная history не получает HISTORY_READY.

API расширен primary.startup и token.decision. Decision read-only; ENTRY_SIGNAL_READY не означает committed OPEN. Snapshot positions различает entry_price/entry_time/entry_local и average_entry/current_local, PnL USDT/% считается по текущему fresh mark, не stale features. Монитор показывает эти поля и прогресс запуска без потери DOM/scroll. Внешний Render/live Bybit по-прежнему не подтверждены в этой сессии.
