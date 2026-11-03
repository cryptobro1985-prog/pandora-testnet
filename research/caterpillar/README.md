# Caterpillar: causal public-data research

Самостоятельный PAPER/RESEARCH-инструмент. Production PANDORA не импортируется и не изменяется. Нет приватных API, торговых ключей, отправки ордеров, deploy-команд или автоматической ротации.

Фиксированная вселенная: **ZEC, HYPE, NEAR, SOL, ENA, 1000PEPE, DOGE, SUI, AAVE, WLD**. Биржевые инструменты — соответствующие `USDT` linear perpetual. `--symbols` принимает только уникальное подмножество этого списка. Отсутствующий инструмент отмечается как отсутствующие данные, замена не производится.

## Установка и проверка

Python **3.12+**. PostgreSQL, Docker и приложение PANDORA этому движку не нужны.

```bash
cd research/caterpillar
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
```

Для точного повторения проверенной среды используйте `.venv/bin/python -m pip install -r requirements-lock.txt` (зафиксированы и транзитивные версии).

Для запуска без тестовых зависимостей достаточно `requirements.txt` (только `websocket-client==1.9.2`). HTTP/CSV/GZIP, статистика и движок используют стандартную библиотеку. На машине должны быть обычные доверенные CA. Сохраняйте TLS verification, `HTTPS_PROXY`, `NO_PROXY`, `SSL_CERT_FILE` и системное хранилище сертификатов. Не добавляйте API keys.

## Историческое исследование: 30–60 дней

```bash
cd research/caterpillar
.venv/bin/python -m caterpillar historical_research \
  --start-date 2026-09-01 --end-date 2026-11-01 \
  --split-date 2026-10-15 \
  --cache .cache/archives --output runs/history-20260901
```

Даты UTC; начало включительно, конец исключительно. Без дат берутся последние 60 **завершённых** суток. `--split-date` необязателен; на границе discovery/evaluation все позиции и незавершённые forward-labels цензурируются, состояние локалов/нормализации прогревается заново. Никакой автооптимизации нет. Если параметры выбирались по discovery, зафиксируйте JSON-конфигурацию **до** отдельного evaluation/realtime-запуска. Не выбирайте лучшую модель по evaluation и затем не называйте тот же период независимой проверкой.

Источник: официальный публичный архив Bybit:

```text
https://public.bybit.com/trading/ZECUSDT/ZECUSDT2026-10-01.csv.gz
```

Используются реальные `timestamp`, `price`, `size`, `side` (Buy/Sell aggressor), `trdMatchID`. Доступность и глубина архива не гарантированы для каждого инструмента и дня. В этой рабочей сессии внешний URL ответил HTTP 403 от сетевого прокси; это **не** доказательство отсутствия архива Bybit. Полный реальный 30–60-дневный прогон здесь не выполнен. HTTP-загрузка, CSV/GZIP/CRC, кэш и декодирование проверены локальным сервером с синтетическими данными, а не выданы за проверку схемы каждого реального архива.

Нужен HTTPS к `public.bybit.com`; для fallback — к `api.bybit.com`. На новой машине сначала проверьте один доступный завершённый день одним токеном, затем запускайте весь период. При HTTP 404/403 или транспортной ошибке данные не выдумываются: день получает статус `unavailable_or_partial`, run завершается с кодом **2** и отчётом неполного покрытия. Для длительного периода ошибки могут означать много безуспешных запросов; сначала устраните сетевой запрет.

Каждый gzip скачивается потоково во временный файл, полностью проверяется CRC до обработки и получает SHA-256 manifest с URL. SHA-256 — локальный контроль воспроизводимости, не независимая подпись Bybit. Повреждённый/неподписанный локальным manifest кэш не принимается молча. Для повторной загрузки сохраните подозрительный файл отдельно и используйте новый каталог кэша. Никаких выключений TLS или подмены checksum.

Обрабатывается один символ/UTC-день за раз, строки читаются потоково. Внутри каждого символа порядок строго хронологический; неупорядоченный архив отвергается. Межсимвольных сигналов, общего капитала и ранжирования нет, поэтому глобальная сортировка всех десяти архивов не нужна. ОЗУ не растёт с числом дней. Кэш и журналы на диске могут быть очень большими; предварительно оцените размер одного дня и доступное место. Данные разных источников не склеиваются в фиктивный tape.

### Явный OHLCV fallback

```bash
.venv/bin/python -m caterpillar historical_research \
  --start-date 2026-10-01 --end-date 2026-11-01 \
  --allow-ohlcv-fallback --output runs/structure-only-fallback
```

Если tick-архив недоступен, публичный V5 REST `/v5/market/kline` пагинируется по минутам. OHLCV поступает только после закрытия бара и пишет отдельные наблюдения диапазона в `candles.jsonl`. **Не** восстанавливает BUY/SELL, внутрибардовую последовательность экстремумов, tick-level подтверждение локалов, PAPER-входы или точные MFE/MAE. Run остаётся `incomplete_coverage` для исследования executed flow. Realtime остаётся полноценным вариантом при недоступной истории.

## Realtime 6-hour audit

Запускает другой исполнитель после исторического анализа; мы не запускали шестичасовую сессию.

```bash
cd research/caterpillar
.venv/bin/python -m caterpillar realtime_audit \
  --duration-seconds 21600 --record-trades \
  --output runs/realtime-oos-001
```

Принимает реальный `publicTrade.*USDT` с `wss://stream.bybit.com/v5/public/linear`, запрашивает подтверждение подписки, посылает heartbeat, переподключается с backoff. Нужен WSS/HTTPS CONNECT к `stream.bybit.com`. Локальная проверка полного адаптера с настоящим WebSocket-сервером включена в тесты. Доступ к реальной бирже в этой сессии не подтверждён.

Ограниченная очередь сортирует события по exchange time с watermark 2 s. Дубликаты ID подавляются в ограниченном LRU; события, пришедшие за watermark, отвергаются. Проверяются отрицательные/NaN цены и размеры, неизвестные стороны/символы, устаревшие и будущие timestamps. Переполнение, reconnect, unusable ingress и разрыв наблюдений >30 s цензурируют позиции/labels, сбрасывают flow/locals и требуют нового прогрева. Разрыв может означать и редкие торги: это сознательно консервативная политика. Потерянную историю нельзя восстанавливать последней ценой.

`--record-trades` сохраняет весь принятый tape для точного replay. Это большой поток на диск. Без него сохраняются блоки, сделки, решения и snapshots, но точное воспроизведение realtime между блоками невозможно.

```bash
.venv/bin/python -m caterpillar replay \
  --input runs/realtime-oos-001/raw_trades.jsonl \
  --output runs/replay-001
```

Replay сохраняет порядок файла и не обращается в сеть. В `raw_trades.jsonl` вместе со сделками записываются явные `GAP`-маркеры disconnect/reset. Replay применяет их до следующих сделок; проверка эквивалентности включает разрыв соединения без временного gap. Вручную подготовленный replay без этих маркеров не воспроизводит неизвестные разрывы исходного feed.

## Причинная логика и исследовательские гипотезы

1. Неперекрывающиеся блоки по **32 принятым сделкам**, не таймер 60/108/300 s. Счётчик не зависит от заполнения deque. Окна и thresholds — фиксированные исследовательские параметры, а не доказанная оптимальная стратегия. MFE/MAE обновляются на **каждом** тике, решение оценивается на границе блока.
2. Baseline — до 256 **предыдущих** блоков, warmup 8. Median/MAD имеют масштабный floor и bounded z; текущий блок не обучает собственный baseline. Равные timestamps дают неизвестный rate (`null`), а не бесконечную интенсивность.
3. Локал проходит `FORMING → UPDATED → CONFIRMED → INVALIDATED`. Новый lower low обновляет кандидата, сбрасывает evidence и не подтверждает разворот. Для подтверждения нужны последующие блоки: отход от экстремума, противоположный responsive control/acceleration, истощение исходного flow либо absorption. Хранятся времена экстремума, образования и подтверждения. Противоположный кандидат начинается в момент подтверждения, без backdating.
4. Два последних подтверждённых High и Low задают UPTREND/DOWNTREND/RANGE. Дополнительные события: IMPULSE, PULLBACK, EXHAUSTION, ABSORPTION, FALSE_BREAK, STRUCTURE_BREAK, REVERSAL, REPEATED_DEFENSE. Sweep с возвратом — наблюдаемый false-break candidate; структурная инвалидизация требует устойчивого встречного control. Это формализованные гипотезы, не распознанная истина.
5. Executed notional и quantity разделены, сохраняются BUY/SELL counts, rates, average/large sizes, imbalance/change, acceleration/deceleration. Price response измеряется в bps и bps на 10k USD агрессора, включая подписанный incremental response на тиках каждой стороны. Это наблюдаемая ассоциация, не доказанное причинное влияние конкретного участника. Large trades сравниваются с robust baseline **средних размеров прошлых блоков**; это эвристика, не откалиброванный trade-size tail quantile.
6. PAPER LONG/SHORT: соответствующий подтверждённый и не пробитый local, price-responsive control, own acceleration, отсутствие own absorption, фильтр несовместимого тренда. Все потенциальные решения и отказы содержат полный snapshot. Запланированная сделка исполняется на следующем тике **с более поздним timestamp**, со slippage. На момент fill проверяется сохранность anchor. Same-timestamp batch не даёт фиктивного заполнения.
7. Девять независимых exit-books: combined, flow_weakening, opposite_flow, price_reversal, absorption, mfe_recoil, local_invalidation, opposite_local, structure_break. Одиночный counterflow в combined не равен transfer; требуется последовательность блоков. MFE recoil требует встречного flow/response и weakening; одного процентного trailing stop нет. У других книг собственные диагностические правила, поэтому результаты не являются общей торговой системой или строго paired испытанием.
8. На каждой сделке: текущий gross PnL, MFE, MAE, MFE timestamp, giveback, estimated executable net MFE/MAE, exit PnL, gross/net capture ratio. `END_MARK` и `CENSORED` не считаются закрытыми прибыльными сделками.
9. После flow-exit сохраняется исходный local и наблюдается коррекция. REENTRY требует его сохранности, факта коррекции и возвращения control. GOOD/BAD_REENTRY определяется по фактическому PAPER-close; незаконченная позиция не получает хорошую оценку. MISSED_REENTRY — только retrospectively eligible, незаполненный candidate с последующим продолжением выше оценённых издержек. FORBIDDEN_REENTRY хранит причины запрета.
10. После выхода измеряются продолжение/просадка на горизонте 256 последующих сделок. EARLY/FAVORABLE_EXIT — hindsight labels для исследования, никогда вход в торговое решение. Forward labels каждого блока на 128 последующих сделках также изолированы от решений; незавершённые horizons цензурируются.

Цена и notional каждого токена ведутся независимо. Fixed-notional по умолчанию 1000 USD **на модель/токен**, fee 4.5 bps за сторону, adverse slippage 2 bps за сторону. Нет общих collateral/equity, compounding, liquidation model, плеча или обещания исполнимой ёмкости. Сводная сумма USD — сумма независимых опытов, не доходность единого портфеля. Funding, bid/ask spread, depth, queue position и market impact не моделируются; их требуется добавить перед финансовыми выводами. Наблюдаемый executed turnover не называется полноценной ликвидностью стакана.

## Результаты и схема

Новый непустой каталог `--output` отвергается: запуски не смешиваются. Формируются:

| Файл | Содержание |
|---|---|
| `CATERPILLAR_RESEARCH_REPORT.md` | Покрытие, каждый профиль, conditional outcomes и evidence gate CATERPILLAR 24/7 |
| `trades.jsonl` | OPEN/REENTRY/CLOSE, fill, fees, полный position и snapshots; END_MARK/CENSORED отдельно |
| `signals.jsonl` | ENTRY/EXIT/HOLD, причины, отложенные и незаполненные решения |
| `rejected_signals.jsonl` | Запреты входа/re-entry с полным snapshot |
| `locals.jsonl` | Причинные стадии локала, ID, extreme/confirmation times, evidence |
| `structure.jsonl` | Trend, sweep/false-break/break/reversal/defense события |
| `flow_events.jsonl` | Полные блоки executed flow, response/efficiency, large trade details |
| `mfe_analysis.jsonl` | MFE/MAE/current/giveback каждого блока и все exit predicates |
| `token_profiles.json` | Все десять `*_PROFILE` по умолчанию: counts, moments, recent quantiles, conditional outcomes |
| `research_summary.json` | Статус, покрытие каждого дня, суммарные exit-books, незакрытые позиции |
| `post_exit.jsonl` | Forward continuation/adverse excursions и retrospective exit/re-entry labels |
| `hypothesis_outcomes.jsonl` | Завершённые/цензурированные forward labels и качества re-entry |
| `data_quality.jsonl` | Дубликаты, late/stale, gaps/reconnects и сбросы |
| `raw_trades.jsonl` | Принятые сделки при `--record-trades` |
| `candles.jsonl` | Явно отдельные OHLCV-only observations |
| `run_manifest.json` | Config, hash, timestamps, версии, источник, fill model, статус |
| `caterpillar_24_7_candidates.json` | Неподтверждённые кандидаты, всегда `deployment_ready: false` |

Все JSONL-строки имеют exchange `ts`, symbol, event_seq. Записи разных символов глобально могут быть не отсортированы; сортируйте для визуализации, не меняйте порядок внутри символа. Moments вычисляются по всем наблюдениям; quantiles честно помечены как последние 2048 samples. Wilson CI — только descriptive: block labels пересекаются, сделки коррелированы. Отчёт показывает lift признака относительно unconditional same-side baseline; это не независимая статистическая значимость. Много сравнений и выбор модели требуют separate walk-forward, block-bootstrap по дням и multiple-testing correction.

Режим завершения: `0` — команды завершились, `2` — неполное покрытие, `1` — ошибка с сохранением частичного отчёта, `130` — прерывание. Даже код 0 не означает достаточный sample size, доходность или удачный six-hour audit. При отсутствии evaluation или достаточных наблюдений вывод о «лучшей стратегии» не делается. Тестовые отчёты не являются торговыми результатами.

## Конфигурация и передача

```bash
.venv/bin/python -m caterpillar historical_research \
  --config config.example.json --start-date 2026-10-01 --end-date 2026-11-01 \
  --output runs/history-frozen-config
```

Список файлов: `caterpillar/model.py` (типы/flow), `engine.py` (locals/structure/PAPER/labels), `sources.py` (архив/REST/replay), `realtime.py` (public WS/ingress), `output.py` (streaming statistics/reports), `__main__.py` (CLI), `tests/`, requirements, конфигурация, `AUDIT.md`, неизменённые входные файлы в `audit_original/`.

Ветка: `research/caterpillar-causal-engine`. Код предназначен для отдельной передачи и запуска. Production deploy и six-hour session не выполнялись. Ограничения и фактически выполненные проверки перечислены в `VALIDATION.md`.
