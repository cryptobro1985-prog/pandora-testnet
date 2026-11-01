# PANDORA Flow v2 — PAPER

Одна flow-driven стратегия, один PAPER-счёт и один монитор. Bybit Public Trades определяют LONG/SHORT, удержание, выход, re-entry и reversal. TOP-5 выбирает рынки раз в час; направление выбирает executed BUY/SELL flow. Реальных ордеров нет.

Эксперимент `pandora_flow_v2` использует отдельную PostgreSQL-схему и начальный баланс **500 USDT**. Однократная инициализация оставляет старые таблицы архивом вне нового account/history. Restart восстанавливает новое состояние и не обнуляет его.

- [Запуск, параметры и архитектура](README_PANDORA_WIN.md)
- [Передача следующему разработчику](PANDORA_WIN_HANDOFF.md)
- [Готовая поставка: результаты, reset и все изменённые файлы](PANDORA_FLOW_V2_DELIVERY.md)
- [Аудит старого decision path и proof нового](PANDORA_FLOW_V2_AUDIT.md)
- [Полный исходный пакет PANDORA_FLOW_V2_COMPLETE.zip](PANDORA_FLOW_V2_COMPLETE.zip)
- Монитор: `/`; JSON: `/api/pandora`
- Сделки: `/api/pandora/history`; журнал: `/api/pandora/events`
- Read-only API: `/openapi.json`

`pandora_risk.py` и `accounting.py` сохранены: dynamic margin/leverage, compounding, fees, slippage estimate и maintenance. Flow-only adapter передаёт risk engine наблюдаемую геометрию исполненных цен. MFE/MAE измеряются; fixed TP/SL и выход по проценту MFE отсутствуют.

Проверки: `python scripts/run_release_tests.py --report validation/release-result.json` с отдельной тестовой PostgreSQL. Active dependency audit: `python scripts/audit_flow_decision_path.py --report validation/flow-decision-path.json`. Результаты software tests не являются бэктестом доходности.

Отдельные результаты acceptance 1–16: `python scripts/run_flow_acceptance.py --report validation/flow-acceptance.json`.

Ветка выпуска — `pandora-flow-v2`. **Render deploy требует отдельной команды пользователя.** Факт reset рабочей базы и live Bybit readiness подтверждаются только проверкой соответствующей среды.
