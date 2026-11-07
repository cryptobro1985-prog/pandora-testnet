# Результат работы: HYPE H1 Local Engine

Дата: 4 ноября 2026. Ветка: `research/hype-h1-local-v5-oi-microstructure-20261104`.
Исходный commit: `5441ca51b20127de3d757731b8ebc4652913cf77`.

**Статус: исследовательский конвейер реализован и проверен на синтетических
контрактах; рыночное исследование заблокировано недоступностью исходных данных.**
100% точность не установлена. Рекомендуемой для торговли конфигурации пока нет.

## Что выполнено

- Причинный bootstrap после шести полных H1, чередование SEEK_HIGH/SEEK_LOW,
  running extreme, немедленная отмена кандидата новым экстремумом, отдельные
  события extension без переписывания ранее опубликованных подтверждений.
- Признаки структуры, ATR, доли отката всего swing, survival, эффективности
  aggressive flow, OI и доступной forward-микроструктуры. Исторический OI имеет
  явный контракт доступности; отсутствующие данные не синтезируются.
- Наблюдаемые стадии climax/absorption/control transfer и обязательный фильтр
  этих стадий для B–F в исследовательском runner. Цены экстремума и подтверждения
  разделены, временная погрешность OHLC сохраняется интервалом.
- Raw-trade обработка и точный replay сохранённых forward frames; коллектор
  сохраняет исходные сообщения, timestamps, последовательность и freshness.
- Хронологические discovery folds, раздельная offline-разметка L6/K2,
  экспорт CSV/JSON, одноразовый запечатанный OOS с hashes кода/данных/настроек.
- Главная метрика учитывает первый принятый сигнал **внутри истинного swing**
  после причинной симуляции. Отдельно показана precision по эпизодам машины.
  Поздняя удачная точка не скрывает ранний false local.
- Подготовлены A–F ablation, HIGH/LOW, volatility regimes, Wilson interval,
  delay/price distance, MAE/MFE и ledgers для анализа false/missed locals.

Алгоритм накопления evidence сейчас — прозрачная некалиброванная эвристика.
Это не обученная sequential likelihood и не доказанное улучшение v5 baseline.
Правила и weights требуют проверки на реальных данных. Называть их оптимальными
или выдавать score за вероятность оснований нет.

## Реально выполненные проверки

Точный итог нового набора тестов сохранён в `results/software_validation.json`.
Проверены причинная prefix invariance, invalidation, alternation, gaps/re-warmup,
время доступности, отсутствие будущих H1/OI, реальные raw-row ordering contracts,
целостность ZIP, границы offline-разметки и сохранение false-first результата.
End-to-end integration выполняет discovery и sealed OOS на **явно синтетическом**
сценарии и проверяет запрет повторения через другой output directory.

`pip check` завершился успешно; production-файлы PANDORA не изменены.
Глобальный legacy release-suite приложения здесь повторно не запускался:
он не относится к новому изолированному research-коду и ранее имел свои ошибки.

## Получение исходных данных: фактический результат

Проверены GitHub Actions API, официальный raw архив Bybit и исторический OI REST.
Все три маршрута возвращают отказ платформенного прокси **на стадии HTTPS CONNECT**
с кодом 403, до обращения к origin. Скачано **0 рыночных файлов**.
Подробные запросы: `results/acquisition/acquisition.json` и `DIAGNOSTICS.md`.

Native Git read работает. Дополнительно изучены ветки
`research/pandora-universal-30d-v1`, `caterpillar-monitor-data` и исходный ZIP:
нужных архивов HYPE там нет. GitHub web artifact URL вернул 404, что не доказывает
отсутствия самого приватного артефакта.

По исходному `scripts/universal_data.py` проверены единицы `ts`: Unix seconds.
Reader конвертирует их в миллисекунды, не путая начало бара с доступностью.
`TICKS-*` artifacts создаются функцией, агрегирующей trades до минут;
они сами по себе не содержат обещанной полной субминутной последовательности.
Автоматический downloader поэтому также запрашивает официальные daily raw files.

В черновик среды добавлены `api.github.com`, `public.bybit.com`, `api.bybit.com`,
`stream.bybit.com`. Повторная проверка runtime показывает enforced restricted,
spec revision 1, custom allowed hosts пуст. Сохранение черновика не применило
сетевую политику. Доступного инструмента активации runtime-конфигурации нет.
Это ограничение платформы невозможно устранить кодом внутри checkout.
Секреты не запрашивались, credentials не извлекались, обход прокси не выполнялся.

## Что НЕ измерено

| Требование | Итог |
| --- | --- |
| 30 дней HYPE minute/raw coverage | Файлы недоступны; не установлено |
| First-accepted precision, recall, false/missed rate | Не измерено |
| Median/P90 delay и distance от экстремума | Не измерено |
| Рыночные MAE/MFE | Не измерено |
| Discovery/walk-forward сравнение A–F | Runner готов; рыночный прогон не выполнен |
| Финальный untouched OOS | Не выполнялся; остаётся нетронутым |
| Forensic analysis каждого реального false/missed local | Невозможен без наблюдений и сигналов |
| Historical OI | Downloader/adapter готовы; данные не получены |
| Historical L50/liquidations за 30 дней | Проверенного полного источника нет |
| Forward OI/book/liquidation прирост | Артефакт недоступен; не установлен |
| Гарантия 100% ранних локалов | Не доказана; обещать её нельзя |

Никакие числа из старого handoff — 76 locals, 3–5 минут, 0.3–0.45% — не
выдаются за повторённые в этой задаче результаты. Пустые либо синтетические
ledgers не подменяют рыночные deliverables. `results/historical/run_status.json`
содержит `blocked`, `market_metrics: null`, `oos_evaluated: false`.

## Воспроизводимое продолжение

Команды установки, acquisition, raw processing, discovery, sealed OOS и forward
replay приведены в `README.md`. После фактического открытия сетевых маршрутов
downloader повторит запросы через штатные proxy/CA и существующую аутентификацию.
Доступ к Actions API при этом ещё требует отдельной фактической проверки;
успешный Git read его не гарантирует. Нельзя заранее объявить все данные
полученными или обещать backfill отсутствующего исторического стакана.

До появления настоящих discovery/OOS результатов эта реализация остаётся
исследовательской основой. Основной боевой runtime не менялся, реальные ордера
не включались.

## Повторная проверка прежнего способа

По дополнительному запросу проверены 1663 версии Git blobs в доступной истории,
включая три исторических ZIP: исходных архивов HYPE не найдено. Прежний локальный
кэш `/tmp/pandora_bybit_archives` в этой машине отсутствует.

В коммите `b76aa569de7f5120a76da3bbe1df30187c7a8c96` найден точный прежний
способ: workflow `extract-5-trade-reports.yml` использовал `gh api
/repos/${GITHUB_REPOSITORY}/actions/artifacts/${ARTIFACT_ID}/zip` с
`GH_TOKEN: ${{ github.token }}` и `actions: read` на GitHub-hosted runner.
Исторический сбор minute/raw тоже выполнялся на Actions runner; временные
файлы оставались в `$RUNNER_TEMP`, а результаты — в artifacts, не в Git.

Точная команда `/artifacts/13278474318/zip` воспроизведена здесь с уже имеющейся
аутентификацией: exit 1, `Forbidden`. Проверка run `41826828580` также вернула
`Forbidden`. Файл ZIP не получен. Это не доказательство истечения artifacts.

Исправлена отдельная ошибка downloader: приватный API больше не проверяется
анонимным urllib перед авторизованным gh-запросом. Добавлены authenticated
preflight и независимый `--source artifacts`, чтобы доступ к Bybit не был
условием получения существующих артефактов. Проверка исправленной команды
в этой машине завершилась exit 2, 0 файлов; точное свидетельство сохранено в
`results/prior_method_attempt/acquisition.json`.

Прежний Actions-механизм реализован в новом manual-only workflow
`.github/workflows/hype-local-v5-artifact-recovery.yml`: существующий runner token,
минимальные read permissions, download/проверки provenance и discovery на найденном
оригинальном minute archive. Код workflow подготовлен локально; удалённого запуска
не было, результаты GitHub Actions не заявляются. Финальный OOS не расходуется.
Сетевые ограничения среды при этом не обходились и не изменились.
