# PANDORA Local Intelligence — результат и запуск

Это исследовательская сборка Quantum + Cortex для HYPEUSDT. Код, исходная история, новые модели и отчёты включены. Торговые ордера не реализованы и не разрешены.

**MONITOR UNCHANGED: YES.** HTML/CSS/JS, публичные маршруты монитора и relay проверяются по исходным SHA-256. Render и GitHub не развёртывались и не изменялись.

## Что подтверждено

Исправлены причинность признаков и время получения REST, отложенная разметка, повторное обучение одного события, согласованное восстановление состояния, блокировка единственного writer, контроль целостности, champion/challenger и изоляция Cortex. Историческое обучение и сравнение завершены; повторять их для запуска не нужно. Финальные проверки находятся в `validation/current/REPORT.json`.

Модель для воспроизводимого shadow-запуска — `linear_temporal_ensemble`: регуляризованная логистическая регрессия + temporal histogram gradient boosting. Выбор сделан по трём walk-forward folds до финального оценивания. На исправленном контрольном периоде она обнаружила **5 из 19** окончательно размеченных локалов: precision **21,7%**, recall **26,3%**. Полезное качество распознавания не доказано. Улучшение Brier не означает решения основной задачи. Архитектура после просмотра OOS не менялась.

Cortex — численный исследователь и изолированный необязательный LLM-адаптер. Из 72 гипотез ни одна не прошла валидацию. Дополнительное улучшение точности Cortex не подтверждено; API и локальная 20B-модель здесь не запускались.

## Установка и проверки

Из корня распакованной сборки:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python scripts/validate_release.py
```

Скрипт проверяет имеющиеся модели и тесты без нового обучения, загрузки рынка, отправки сообщений или изменений монитора. Зависимости зафиксированы; фактический набор — `docs/VALIDATED_DEPENDENCIES.txt`.

## Первый запуск на новых данных

Требуется HTTPS/WSS-доступ к `api.bybit.com` и `stream.bybit.com`. В текущей облачной среде оба назначения блокируются прокси с 403 (`docs/NETWORK_CHECK.json`); сохранённые домены необходимо применить в настройках среды и проверить новым соединением. Ключи Bybit для публичных данных не нужны. TLS verification отключать нельзя.

Подготовьте новую папку один раз, не поверх существующего runtime:

```bash
mkdir runtime
cp artifacts/quantum_research/champion/local_only_model.pkl runtime/
cp artifacts/quantum_research/champion/local_only_model.pkl.sha256 runtime/
cp artifacts/quantum_research/LOCAL_RELATIONSHIP_MEMORY.json runtime/
cp artifacts/quantum_research/HISTORICAL_TRAINING_REPORT.json runtime/
```

В отдельных терминалах из корня сборки:

```bash
PYTHONPATH=src .venv/bin/python -m research.hype_local_only.live_daemon \
  --capture-root capture --checkpoint-dir runtime --minutes 30
```

```bash
(cd src && ../.venv/bin/python research/hype_local_v5/resilient_capture.py \
  --minutes 30 --chunk-minutes 10 --output ../capture)
```

```bash
CORTEX_BACKEND=disabled PYTHONPATH=src .venv/bin/python -m research.hype_local_only.cortex_daemon \
  --checkpoint-dir runtime --minutes 30 \
  --research-memory artifacts/cortex_research/CORTEX_RESEARCH_MEMORY.json
```

Численный inference не ждёт Cortex. Collector возвращает ненулевой статус при отсутствии необходимых рыночных наблюдений. Проверяйте свежие `LOCAL_ONLY_STATUS.json`, `LOCAL_EVENTS.jsonl`, `LOCAL_LIVE_LABELS.jsonl`, `CORTEX_LOCAL_ONLY_STATUS.json` и `RESILIENT_CAPTURE_MANIFEST.json`; наличие PID не доказывает готовность.

Публикация статуса существующему монитору требует отдельного явного флага `--publish-existing-monitor` и настроенного адреса. Обновление issue требует `--publish-issue`. Они не используются при локальной проверке. HTML, маршруты и Render менять не требуется. Файлы workflows — предложения для ревью; они не запускались.

## Восстановление и rollback

Повторно запускайте тот же producer с прежней папкой `runtime` и сохранённым `capture`. Не копируйте seed поверх действующего состояния. `RUNTIME_CURRENT.json` и вся `runtime_generations/` вместе хранят модель, learner, pending labels, dedup и позиции чтения. При повреждении текущего поколения используется проверенный fallback. Если целого поколения нет, процесс останавливается, а не начинает обучение молча заново. Writer lock запрещает два producer на одной папке.

Для проверенного предыдущего поколения:

```bash
PYTHONPATH=src .venv/bin/python -m research.hype_local_only.live_daemon \
  --capture-root capture --checkpoint-dir runtime --rollback-generation GENERATION_NAME
```

Для сохранения копии остановите свои producer/Cortex и сохраните всю папку runtime. Не переносите только pickle модели. Старые PID в `artifacts/latest_checkpoint` — архивные доказательства, не действующие процессы.

## Артефакты и ограничения

- `docs/QUANTUM_AUDIT.md`, `CORTEX_AUDIT.md`, `DATA_AUDIT.md`, `FEATURES_AUDIT.md` — аудит и ограничения.
- `artifacts/quantum_research/HISTORICAL_TRAINING_REPORT.json` — исправленное сравнение всех моделей, сторон, горизонтов, задержек и калибровки.
- `SUPERSEDED_INVALID_SELECTION_REPORT.json` — первый эксперимент с ошибкой времени созревания validation labels; его метрики недействительны.
- `champion/local_only_model.pkl` — замороженный исследовательский seed без обучения на финальном OOS; production promotion не выполнено.
- `linear_alternative.pkl`, `nonlinear_alternative.pkl`, `online_challenger.pkl` — сохранённые альтернативы.
- `full_history_research_only.pkl` — обучение на всей созревшей истории; `independent_oos=False`, не оценённый champion.
- `artifacts/cortex_research/` — проверенные и отклонённые гипотезы, память и тесты.
- Исходные `artifacts/latest_checkpoint`, `latest_evidence`, исторические gzip и старые отчёты сохранены; они не являются свежим live-статусом.

Обучающие признаки используют только завершённые M1 OHLC и причинные temporal summaries. Исторические L50, liquidation и receive latency не выдумывались. Полное текущее использование 86 входов не равнозначно доказанной прогностической полезности всех 86. В истории 77 строгих/123 внутренних локала, независимых подтверждённых событий мало. Новые dense proposals вне исторической six-hour выборки остаются watch-only. Независимый forward cohort должен завершиться до продвижения модели; по умолчанию 64 группы с девятичасовым разнесением требуют недель наблюдений.

Готовность к live paper-validation: программные механизмы проверены на воспроизведении и синтетическом потоке; живое подключение заблокировано, требуемое качество пока не достигнуто. Реальные ордера запрещены. До отдельного решения необходимы новые независимые forward-данные, приемлемые precision/recall и доверительные интервалы, калибровка, проверка режимов/издержек и устойчивости live pipeline.

Собрать ZIP повторно без обучения:

```bash
.venv/bin/python scripts/package_release.py --output ../PANDORA_LOCAL_INTELLIGENCE.zip
```
