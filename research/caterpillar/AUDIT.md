# Аудит переданного ZIP

Проверены все 3 исходных файла. Оригиналы сохранены в `audit_original/`; они не используются новым CLI.

| Находка | Следствие | Реализация |
|---|---|---|
| `len(deque) % 20` после maxlen=20000 | После заполнения расчёт на каждом тике; иной алгоритм в длинном запуске | Независимый счётчик неперекрывающихся блоков; regression test за границей history capacity |
| Кластеры 120 тиков с шагом 20 | Сильно перекрывающаяся evidence и зависимые z | Non-overlap blocks, baseline только из прошлого; forward labels всё ещё коррелированы, явно обозначено |
| Нет стадий и времени подтверждения local | Нельзя отличить новый минимум от подтверждённого разворота | Local ID, FORMING/UPDATED/CONFIRMED/INVALIDATED, последующее evidence, отдельное confirmation time |
| Extreme и открытие на одном текущем кластере | Неявное предположение об исполнимой цене | Только позднейший timestamp после решения, slippage/fees, anchor revalidation |
| MFE обновляется только при signal / regime !=0 | Межблоковые экстремумы теряются | Mark every accepted tick, отдельные MFE/MAE и timestamps |
| CLOSE очищает position до log | Теряется состояние закрываемой сделки | Полный position и exit snapshot в CLOSE |
| Reentry_side без сохранности anchor/коррекции | Неограниченный churn и ложный re-entry | Anchor ID, наблюдённая коррекция, validity/horizon checks, forbidden/missed/good/bad labels |
| Нулевой MAD заменён epsilon | Неустойчивые огромные z | Robust scale floor плюс bounded z |
| Нет event ID, monotonicity, gaps | Дубликаты/late/stale создают flow и прибыль | Bounded reorder/LRU, invalid/late rejection, censor/reset/warmup |
| `time.time()` вместо exchange event time в log | История смешана со временем replay | Exchange timestamps; receive time отдельно |
| Нет historical / WS adapters | Невозможно запустить реальный аудит | Streaming official daily archives, strict decoder, REST-only fallback, public WS ACK/heartbeat/reconnect |
| Нет costs/post-exit/control groups | Нельзя оценить качество exit и claims PnL | Fees/slippage, независимые exit hypotheses, forward outcomes, same-side baseline, OOS reset |
| Нет профилей/отчёта | Нельзя сравнить токены | Все 10 профилей, machine-readable evidence и Markdown report |

Оригинальная логика не доказывала прибыльность. Новая реализация тоже не делает такого утверждения: thresholds и классификации — пререгистрируемые гипотезы. Наблюдаемый `large_trade` не идентифицирует участника рынка. Абсолютно точный executed BUY/SELL из OHLCV невозможен, и fallback этого не делает.

Сохраняются явные ограничения: фиксированная модель slippage без стакана/impact/funding, коррелированные горизонты, независимые notional-books вместо общего капитала, bounded dedup history и conservative gap policy. Автоматического выбора лучшей 24/7 стратегии на том же sample нет.
