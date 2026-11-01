# Pandora Win — audited PAPER source

Глубокий аудит и актуальные правила риска: [DEEP_AUDIT.md](DEEP_AUDIT.md). Монитор обновлён для телефона; JSON API1.1 и read-only `/openapi.json` доступны для внешнего клиента/ChatGPT. Убытки не скрываются; 100% win rate не гарантируется.

Python 3.12, PostgreSQL 17, Bybit V5 public REST/WebSocket. Реальные ордера и приватные торговые API отсутствуют. Старт новой базы — $500; существующий баланс и история при старте сохраняются.

## Архитектура и файлы

| Файл | Ответственность |
| --- | --- |
| `app.py` | Супервизор потоков, HTTP, PostgreSQL, lease, атомарные открытия/закрытия, восстановление свечей |
| `pandora_scanner.py` | Все рыночные ticker streams, относительный ranking, Top-5, кандидатный пул, FADING/ROTATE_OUT |
| `pandora_flow.py`, `market_data.py` | Public Trades, notional/quantity, окна, скорость объёма, dominance, price response |
| `exchange_trade_adapter.py`, `bybit_market_stream.py` | Нормализация Bybit, ACK, reconnect, дедупликация, контроль времени и свежести |
| `h1_structure.py`, `pandora_locals.py` | Подтверждённые H1-локалы, online forming-extremes, закрытая M15-структура |
| `local_order_flow.py` | Вход, поглощённые откаты, структурное подтверждение выхода, зеркальный re-entry |
| `pandora_risk.py` | Динамическая маржа и плечо 10–50x, stress geometry и модель maintenance; без SL/TP |
| `pandora_api.py` | JSON contract1.1 и read-only OpenAPI |
| `pandora_win_core.py` | Compounding, state machine доливок, quantity-weighted average entry, MFE/MAE |
| `pandora_runtime.py` | Состояния токенов, управление LONG/SHORT, pyramiding, semantic audit, восстановление |
| `engine_store.py`, `accounting.py` | Single-writer lease/fence, линейный perpetual PnL и моделируемые комиссии |
| `strategy1_monitor.py` | Монитор, выбранные токены, позиция/сила сторон/MFE, доливки и действия |
| `scripts/run_release_tests.py`, `tests/` | Проверки программы на синтетических данных, PostgreSQL и loopback WebSocket |
| `scripts/package_source.py` | Полный source ZIP без секретов/баз/venv, SHA-256 manifest |

Сравнительные движки 1.1/1.3/1.4 сохранены для совместимости с существующими данными, но их торговые циклы по умолчанию выключены. Основной работающий движок — Pandora Win.

## Scanner

Metadata REST отбирает только Trading LinearPerpetual с расчётом в USDT. Шардированные WebSocket получают tickers по всему разрешённому рынку. REST tickers используется для bootstrap/recovery при отсутствии свежего потока. Ranking обновляется раз в секунду из сообщений, а не из 60-секундного REST polling.

Параметры ranking: текущий 15s/60s price movement, acceleration, наблюдаемая volatility, turnover/скорость turnover, executed volume и его изменение, BUY volume, trade count/rate, устойчивость изменения цены и доступный spread. Используется средний относительный percentile rank, без обучения и подбора весов. SELL volume хранится отдельно и участвует в executed imbalance/control и price response; число сделок не заменяет объём.

Все market tickers наблюдаются постоянно. Executed tape прогревается для ограниченного кандидатного пула (по умолчанию 30), выбранных пяти и удерживаемых позиций/watch. Это ограничивает нагрузку, сохраняя быстрое обнаружение новых кандидатов по market-wide tickers. Новый токен не получает торговое разрешение до свежего собственного public-trade потока и структуры. При недостатке свежих активных кандидатов список может содержать меньше пяти — отсутствующие данные не подставляются.

После ротации открытая позиция остаётся подписанной и управляемой в FADING. Новые входы и доливки по исключённому токену не создаются. После закрытия он получает ROTATE_OUT; старый watch не запускает повторную торговлю по затухшему токену.

## Locals, LONG и SHORT

H1-экстремум сравнивается с четырьмя предыдущими закрытыми H1. Последующий закрытый H1 с более низким high подтверждает LOCAL HIGH; с более высоким low — LOCAL LOW. Два одновременных неоднозначных подтверждения не выбирают направление. Разрывы/устаревшая история отклоняются.

Формирующаяся свеча читается только с фактической меткой её online-наблюдения. Forming low/high обновляется при новых экстремумах, сохраняя отдельный `confirmed_local`. Если прежний low/high пробит в сторону его продолжения, новые входы от старого local блокируются до подтверждения. Исторический окончательный OHLC незакрытой на момент решения свечи не используется как будто был известен заранее.

Закрытая последовательная M15-структура после наблюдавшегося экстремума вместе с устойчивым executed control может подтвердить executable direction раньше следующего закрытого H1. Исторический H1-anchor остаётся видимым отдельно; источник подтверждения записывается. Один wick сам по себе не переворачивает направление.

LONG требует разрешающей структуры и BUY executed majority с подтверждающим движением цены; SHORT зеркален. Поток, mark, contract leverage и актуальная проверка H1 повторно проверяются при выделении маржи. Старый restored-anchor не даёт права на новый риск до проверки текущих свечей процессом.

## Executed flow и удержание

Окна 5/15/30/60/180/300 секунд содержат фактические исполнения. Публикуются BUY/SELL USD и quantity, imbalance/change, trade count/rate, volume velocity/acceleration, dominance duration, price response и absorption. Неполное окно явно помечено `complete=false`, его объём не экстраполируется в «готовую статистику».

Первое встречное давление переводит позицию в наблюдение. Новый благоприятный экстремум поглощает малый откат; его размер и граница сохраняются. Выход требует встречного executed control и структурного пробоя предыдущего поглощённого отката либо неудачного ретеста продолжения. Подтверждённый противоположный local с устойчивым встречным контролем также завершает позицию. По итоговому ТЗ процентного SL/TP/MFE-giveback выхода нет: закрытие определяется сменой executed control и структурой цены. MFE остаётся статистикой.

MFE/MAE, peak MFE USD, текущий PnL, giveback, flow/local state, average entry и pyramid level обновляются по живым данным и checkpoint в PostgreSQL примерно раз в секунду. Финальная цена/контекст и giveback сохраняются при закрытии.

## Re-entry, reversal и pyramiding

Re-entry сохраняет сторону/структуру выхода и требует зеркального подтверждения завершения отката с возвращением executed control. Счётчик последовательных re-entry не ограничен. Новый подтверждённый противоположный local и fresh executed control разрешают LONG↔SHORT; закрытие предыдущей стороны и открытие новой имеют отдельные атомарные записи и semantic reversal event. Незавершённое открытие после рестарта может быть продолжено без повторного начисления PnL.

Pyramiding — отдельная state machine. Позиция должна быть прибыльной после моделируемых комиссий, local должен оставаться валидным, несколько наблюдаемых flow-окон — подтверждать сторону, а цена и executed side-volume/velocity — превосходить предыдущий импульс. При absorption, старом событии, недостатке маржи или достижении явного risk cap доливки нет. После ADD состояние возвращается в ожидание нового импульса.

По умолчанию максимум две доливки. Запрошенная добавка маржи динамически масштабируется силой сигнала: базовые 10% × (0.5 + signal_strength), то есть 5–15% текущего equity до ограничений collateral/плеча. Общая маржа одной позиции — до 40% equity. Это объявленные ограничения риска, не найденные оптимизацией параметры. Каждая ADD хранится отдельно со временем, ценой, объёмом, маржой, total notional, average entry, flow/locals и MFE до/после. Average entry = суммарный entry notional / суммарное количество контрактов. Финальный PnL равен сумме PnL отдельных входов при той же цене выхода.

Базовая новая позиция — динамически10–30% текущего mark-to-market equity по марже, плечо10–50x с ограничением contract maximum и модельной maintenance-геометрией. Ниже10%/10x позиция не открывается; недостаток обеспечения означает пропуск, не маленькую частичную позицию. Сумма следующего входа считается после фактического PnL предыдущих закрытий: compounding работает в обе стороны. Паузы по дневному PnL, просадке или серии убытков отсутствуют. Stress-reference — только планировочная оценка, не stop/TP. Результат modeled maintenance breach учитывается честно и может быть отрицательным.


## Persistence, state machine и audit

Канонические таблицы `local_v12_*` сохранены. Добавлены `pandora_token_state`, `pandora_runtime_state`, `pandora_pyramid_adds`. Lease/fence защищает каждого писателя и атомарные изменения денег. На restart восстанавливаются позиции, усреднённый вход, доливки, MFE/MAE, local/pending, scanner selection, watch и account; свежесть рыночных наблюдений не восстанавливается из старого checkpoint.

Состояния: SELECTED, FORMING_LOCAL_LOW/HIGH, LONG/SHORT_READY, LONG/SHORT, LONG/SHORT_PYRAMID, LONG/SHORT_WEAKENING, WAIT_REENTRY, FADING, ROTATE_OUT. Audit включает выбор/ротацию токена, forming/confirmed local, OPEN/ADD/CLOSE, REENTRY/REVERSE, HOLD/WAIT и FLOW_STALE с market context. Повторяющиеся HOLD/WAIT checkpoint журналируются с ограниченной частотой; позиции/деньги журналируются транзакционно. История автоматически не удаляется.

## Запуск PAPER

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL='postgresql://USER:PASSWORD@HOST:5432/pandora_paper'
python app.py
```

URL выше — шаблон. Используйте отдельную PAPER PostgreSQL и задавайте реальные учётные данные безопасно в окружении. Для public Bybit не нужен API key. Не запускайте второй engine на той же базе. Перед обновлением действующей базы используйте штатный backup PostgreSQL.

| Переменная | Значение по умолчанию / назначение |
| --- | --- |
| `DATABASE_URL` | Обязательное PostgreSQL-подключение |
| `PORT` | `10000` |
| `PANDORA_SCAN_CANDIDATES` | `30`, кандидатный executed-flow pool |
| `PANDORA_SCANNER_SHARDS` | `4`, 1–8 market ticker sockets |
| `BYBIT_AUX_WS_SHARDS` | `2`, kline/quote shards |
| `PANDORA_MAX_ADDS` | `2`, максимальное число ADD на позицию |
| `PANDORA_ADD_MARGIN_FRACTION` | `0.10`, доля equity на ADD |
| `PANDORA_MAX_POSITION_MARGIN_FRACTION` | `0.40`, предел маржи позиции с ADD |
| `PANDORA_COMPARISON_ENGINES` | `0`, включать старые сравнения только явным `1` |
| `PANDORA_CONTROL_TOKEN` | Необязательный bearer для ручного PAPER-close |
| `RENDER_EXTERNAL_URL` | Keepalive; локально задайте адрес своего локального сервера |
| `RENDER_GIT_COMMIT` | Версия в health/monitor |

Нужен HTTPS/WSS доступ к `api.bybit.com`, `stream.bybit.com`. Сохраняйте TLS verification и CA/proxy окружения. Никаких реальных ключей/secret/database dumps в ZIP нет.

HTTP: `/`, `/openapi.json`, `/api/pandora` (также `/api/dashboard`), `/api/strategy1/history`, `/api/strategy1/events`, `/health`, `/health/risk`. JSON содержит account, пять token rows, открытые/закрытые позиции, adds, re-entries, reversals, rotations и подробные flow/local contexts. История сделок и событий поддерживает cursor pagination. HTTP 200 `/health` означает работающий процесс, а не доступность рыночной торговли.

## Проверка программы

Установите `requirements-dev.txt`; укажите `DATABASE_URL` отдельной тестовой базы и `PANDORA_TEST_DATABASE_URL_FILE` с тем же URL. Запустите `python scripts/run_release_tests.py --report validation/release-result.json`. Интеграции не должны быть пропущены. Это синтетические функциональные проверки, а не бэктест, оптимизация или расчёт исторической доходности. Дальнейшая проверка рыночного поведения проводится отдельно.

## Уточнения после глубокого аудита

Полный отчёт и актуальные параметры — DEEP_AUDIT.md. Фиксированных SL/TP/MFE-процентов и PnL-пауз нет. Минимумы нового входа —10% текущего equity и10x; максимум плеча50x при допустимой контрактной/model geometry. Добавление плеча не создаёт equity и не освобождает старый collateral. Биржевая liquidation-модель здесь не воспроизводится точно.

Входу нужен15-секундный реально наблюдавшийся tape, подтверждающие объёмы/price response и local. Быстрый5/15s контрконтроль для выхода отделён от60s entry-контекста, чтобы старый объём не задерживал закрытие. Stale mark блокирует новый риск; новый убыток не создаёт паузу. Убыточные строки не удаляются из статистики.

Монитор обновляет keyed DOM из JSON каждые2 секунды. Порядок карточек меняется только вручную кнопкой rank; вкладка и прокрутка сохраняются. Scanner pool и все locals доступны раскрывающимися секциями. PnL счёта — USDT/% от starting equity, сделки — USDT/% от её маржи. `/api/pandora` публикует timestamps, источник readiness и причины отказов. Read-only `/openapi.json` можно импортировать в совместимый клиент ChatGPT; это не автоматическое подключение клиента и не подтверждение deploy на Render.
