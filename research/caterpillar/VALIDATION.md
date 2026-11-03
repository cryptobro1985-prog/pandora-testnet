# Фактические проверки

Среда: Debian 13, Python 3.12.14. Независимый research venv; закреплённые прямые зависимости и полный `requirements-lock.txt`.

- `python -m pip install -r requirements-lock.txt`: выполнено; повторная установка не меняет зависимости.
- `python -m pip check`: `No broken requirements found`.
- `python -m unittest discover -s tests -v`: **28 tests, 28 passed, 0 skipped**.
- Настоящий loopback HTTP-сервер: gzip download, CRC, CSV schema, checksum manifest и повторное чтение кэша.
- Настоящий loopback WebSocket-сервер: подписка/ACK и полный realtime-адаптер, 32 синтетических события и 2 flow-блока. Это не подключение к Bybit.
- CLI `replay`: **14 720 синтетических сделок, все 10 символов**, статус completed, сформированы все отчёты и журналы. Были реальные исполнения PAPER-модели и закрытия в синтетической проверке; финансовые числа тестовой последовательности не являются рыночными результатами.
- Prefix invariance: будущие события не меняют уже записанные locals/structure/flow/decisions.
- Проверены MFE на каждом тике, short/long costs, lower-low без подтверждения, next-timestamp fills, warmup/split, re-entry success и запреты, sustained transfer, false-break, overflow, same-timestamp memory bounds, duplicates/late/stale/gap, raw replay с disconnect-маркерами, невозможность flow/PAPER-entry из OHLCV.
- `compileall`: выполнен для нового пакета, scripts и tests.
- Существующие tracked production-файлы не менялись.

Не выполнены: реальный 30–60-дневный анализ, six-hour audit, deploy, получение live-статистики. URL официального архива в этой среде получил HTTP 403 от сетевого прокси. Полнота архива/реальная схема каждого дня и доступ к живой Bybit не подтверждены.

До разработки research был запущен существующий release-runner PANDORA на отдельной локальной PostgreSQL: 218 tests, 31 failures, 9 errors. Это отдельный набор на исходном commit e392ad88044a43f91869ef27aacf6878853e2d9a; его причины не входят в данную research-задачу, и production-код не исправлялся. Успех нового research-набора не означает исправления исходного приложения.

Для повторения offline CLI smoke (не торговое исследование):

```bash
python scripts/make_synthetic_fixture.py /tmp/caterpillar-synthetic.jsonl
python -m caterpillar replay --input /tmp/caterpillar-synthetic.jsonl --output runs/synthetic-smoke
```

Fixture generator и движок отказываются перезаписывать существующие результаты. Для нового прогона используйте новые пути. Реальные данные и их результаты в репозиторий не добавлялись.
