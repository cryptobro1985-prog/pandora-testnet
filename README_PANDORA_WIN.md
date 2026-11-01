# Pandora Win — PAPER

Pandora Win — единственная стратегия приложения. Python 3.12, PostgreSQL 17, Bybit V5 Public REST/WebSocket. Приватные торговые API и реальные ордера не используются.

## Чистый счёт и сохранение состояния

Приложение использует только выделенное пространство таблиц `pandora_win_*`. При первом создании счёта баланс равен **500 USDT**, список сделок пуст, realized PnL равен нулю. Следующие запуски восстанавливают позиции, баланс, locals, MFE/MAE, доливки, scanner selection и ожидания перезахода этого счёта. Данные не стираются при каждом restart/deploy.

Текущее приложение не читает и не объединяет другие пространства таблиц. Физическое удаление данных за пределами `pandora_win_*` не является частью штатного запуска. Доступ к рабочей базе и факт применения изменений на Render должны подтверждаться отдельно.

## Компоненты

| Файл | Назначение |
| --- | --- |
| `app.py` | HTTP, супервизор, состояние счёта, атомарные открытия/закрытия, восстановление |
| `pandora_scanner.py` | Market-wide tickers, ranking, активная пятёрка и ротация |
| `market_data.py`, `pandora_flow.py` | Executed BUY/SELL volume, окна, velocity, dominance и price response |
| `exchange_trade_adapter.py`, `bybit_market_stream.py` | Bybit normalization, timestamps, ACK, reconnect, deduplication и freshness |
| `h1_structure.py`, `pandora_locals.py` | Confirmed/forming H1 locals и online M15 confirmation |
| `local_order_flow.py` | Вход, наблюдение отката, структурный выход и re-entry |
| `pandora_win_core.py`, `pandora_risk.py` | Compounding, pyramiding, average entry, MFE/MAE, динамическое обеспечение/плечо |
| `pandora_runtime.py` | State machine токена, управление позицией и журнал решений |
| `pandora_bootstrap.py`, `pandora_decisions.py` | Приоритетная загрузка H1/M15 и понятные стадии ENTRY/WAIT |
| `engine_store.py`, `accounting.py` | Single-writer lease/fence и расчёт net PAPER PnL |
| `pandora_monitor.py`, `pandora_api.py` | Мобильный монитор и read-only API |
| `scripts/run_release_tests.py`, `tests/` | Проверки программы с отдельной PostgreSQL и локальным WebSocket |
| `scripts/package_source.py` | Полный ZIP исходников и SHA-256 manifest без секретов/баз/venv |

## Scanner и ротация

Metadata REST выбирает Trading LinearPerpetual с расчётом в USDT. Шардированные WebSocket наблюдают тикеры всего этого рынка. REST используется для bootstrap/recovery и данных, которых нет в потоке.

Ranking обновляется раз в секунду: текущие movement/acceleration, наблюдаемая volatility, turnover, executed volume/velocity/change, BUY/SELL participation, trade rate, устойчивость движения и доступная ликвидность. Признаки получают равные относительные percentile ranks; это не обучение и не оптимизация доходности.

Public Trades прогреваются для кандидатного пула (по умолчанию 30), выбранных пяти и удерживаемых позиций/watch. Затихший токен уступает место активному. Один stale-токен не замораживает весь scanner; глобально недоступные данные сохраняют selection без выдуманной ротации. Активная высокообъёмная коррекция может оставаться кандидатом для SHORT. Открытая позиция исключённого токена продолжает получать управление до закрытия. При недостатке подходящих свежих рынков список содержит меньше пяти.

## Locals и executed control

Confirmed H1 local сравнивается с четырьмя предыдущими закрытыми H1. Последующая закрытая структура подтверждает экстремум. Forming local обновляется только по реально наблюдавшейся свече; исторический окончательный OHLC не используется как будущая информация. Confirmed и forming показаны отдельно. Пробитый экстремум или stale forming блокирует новые входы от непроверенной структуры.

Закрытая M15-структура после наблюдавшегося экстремума вместе с подтверждённым executed control может подтвердить направление до следующего закрытого H1. Один wick не переворачивает направление.

Окна 5/15/30/60/180/300 секунд содержат фактический USD notional и quantity: BUY/SELL, imbalance/change, count/rate, volume velocity/acceleration, dominance duration и price response. Количество сделок не заменяет их объём. Неполные окна явно помечены; наблюдения не экстраполируются.

Новый вход и re-entry требуют согласованного entry-контекста и актуального local. Для подтверждённого структурного выхода используется отдельный быстрый контроль 5/15s, чтобы минутный объём не задерживал захват контроля другой стороной. Нужны минимум 15 секунд реально наблюдавшегося tape, а не просто время жизни сокета. Перед записью входа поток проверяется повторно: исчезнувший BUY-control не разрешает LONG.

## LONG/SHORT, re-entry и reversal

LONG открывается при разрешающей структуре и подтверждённом BUY control; SHORT зеркален. Первый встречный импульс сам по себе не закрывает сильное движение. Свежий благоприятный экстремум поглощает малый откат; встречный контроль и структурный пробой/неудачный ретест подтверждают выход. Новый противоположный local с контролем другой стороны может завершить позицию и разрешить отдельное открытие обратной стороны.

Re-entry требует зеркального подтверждения окончания отката и возвращения control. Число последовательных re-entry не ограничено. Фиксированных процентных SL/TP, MFE-giveback выходов, дневных PnL-пауз и остановки после серии убытков нет. MFE/MAE/giveback измеряются и сохраняются. Модельное исчерпание maintenance учитывается честно, а не заменяется положительным результатом.

## Маржа, плечо и pyramiding

Новый вход — **не менее 10% текущего equity по марже и не ниже 10x**. Подтверждение объёмом, реакция цены и структура динамически выбирают маржу 10–30% и плечо 10–50x, затем применяются контрактный максимум, доступное обеспечение и модельная геометрия adverse range/maintenance/costs. Если минимальная сделка не обеспечена, она отклоняется целиком.

После закрытия net PnL меняет баланс, который участвует в следующем расчёте: compounding работает и после прибыли, и после убытка. Изменение плеча само по себе не создаёт equity.

ADD возможен только в прибыльную позицию при валидном local, новом ценовом импульсе и усилении executed side-volume/velocity. Запрос добавки масштабируется силой сигнала: базовые 10% × (0.5 + signal_strength), то есть 5–15% equity до ограничений обеспечения. По умолчанию максимум две доливки и до 40% equity по общей марже позиции. Эти параметры управляют экспозицией, не являются SL/TP или PnL-паузой.

Каждая доливка хранится отдельно. Average entry = суммарный entry notional / суммарное количество контрактов. Total notional, average entry, маржа, плечо и ADD-запись обновляются одной fenced-транзакцией. Ранее внесённый collateral не освобождается как мнимая прибыль; выбранное contract leverage и эффективное notional/retained margin показаны отдельно.

## Запуск

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL='postgresql://USER:PASSWORD@HOST:5432/pandora_paper'
python app.py
```

URL — шаблон. Задавайте настоящее подключение безопасно в окружении Render/машины, не в исходниках и не в чате. Для Public Bybit не нужен API key. Не запускайте два движка на одном PAPER-счёте. Нужен HTTPS/WSS доступ к `api.bybit.com` и `stream.bybit.com`; сохраняйте TLS verification и CA/proxy окружения.

Основные параметры:

| Переменная | По умолчанию |
| --- | --- |
| `DATABASE_URL` | Обязательное PostgreSQL-подключение |
| `PORT` | `10000` |
| `PANDORA_SCAN_CANDIDATES` | `30` |
| `PANDORA_SCANNER_SHARDS` | `4` |
| `BYBIT_AUX_WS_SHARDS` | `2` |
| `PANDORA_MIN_MARGIN_FRACTION` / `PANDORA_MAX_ENTRY_MARGIN_FRACTION` | `0.10` / `0.30` |
| `PANDORA_MIN_LEVERAGE` / `PANDORA_MAX_LEVERAGE` | `10` / `50` |
| `PANDORA_MAX_ADDS` | `2` |
| `PANDORA_ADD_MARGIN_FRACTION` | `0.10` до масштабирования сигналом |
| `PANDORA_MAX_POSITION_MARGIN_FRACTION` | `0.40` |
| `PANDORA_CONTROL_TOKEN` | Необязательный bearer для ручного PAPER-close |
| `RENDER_EXTERNAL_URL` | Адрес своего сервиса для keepalive |
| `RENDER_GIT_COMMIT` | Версия в health/monitor |

Stress-reference в risk plan служит только планированию размера, не является stop-приказом. Maintenance — приближённая PAPER-оценка; default assumptions могут ограничить плечо ниже 50x. Funding, реальные fills, slippage и биржевые tiers этой моделью не подтверждаются. Прибыль, 100% win rate и отсутствие ликвидации не гарантируются.

## Старт, монитор и API

После восстановления счёта сразу запускаются metadata/ticker/WS workers. H1/M15 для выбранных пяти загружается в отдельном pool из пяти workers, фоновые кандидаты — в одном worker. Общий history limiter — 5 REST-запросов/с, приоритет перечитывается каждые 0.2s; ошибка одного контракта имеет собственный backoff. Обзор начинается без искусственной задержки, фактическая готовность зависит от сети, Bybit, структуры и наблюдений tape.

Монитор `/` адаптирован для телефона. Keyed JSON polling каждые 2s сохраняет карточки, их порядок, вкладку и прокрутку. У позиции видны первый вход/время/local, средний вход после доливок, текущие confirmed/forming locals, net PnL USDT/% от маржи. PnL счёта считается от starting equity. Stale mark показывает недоступный PnL, не положительное число из устаревшего кэша.

`GET /api/pandora` возвращает корневой объект `pandora`: account, выбранные токены, startup, позиции, сделки, ADDs, journal и runtime. `startup` показывает обзор контрактов и ENTRY/WAIT с причинами. Готовый сигнал не считается committed позицией до записи исполнителя.

- `/api/pandora/history` — сделки с cursor pagination.
- `/pandora/history` — страница сделок.
- `/api/pandora/events` — журнал решений.
- `/openapi.json` — read-only HTTP-схема для совместимого клиента ChatGPT.
- `/health` — состояние процесса.
- `/health/risk` — свежесть данных и успешное исполнение; недоступные данные дают неготовность.

Публикация source-кода и наличие OpenAPI не означают автоматического подключения клиента ChatGPT или подтверждённого deploy на Render.

## Проверка программы

Установите `requirements-dev.txt`. Укажите `DATABASE_URL` отдельной тестовой PostgreSQL и `PANDORA_TEST_DATABASE_URL_FILE` с тем же URL. Запустите:

```bash
python scripts/run_release_tests.py --report validation/release-result.json
```

Runner не принимает пропущенные интеграционные проверки как готовность. Проверки используют синтетические входы, настоящий loopback WebSocket и PostgreSQL, а не бэктест/оптимизацию доходности. Секреты, базы, venv и Git metadata в source ZIP не включаются.
