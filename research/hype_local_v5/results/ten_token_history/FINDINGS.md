# История сбора данных по десяти токенам

Проверены 59 опубликованных веток, 1869 версий Git blobs и 543 файла внутри
исторических ZIP. Подробности: bybit_key_audit.json.

## Конкретный 30-дневный сбор

- Commit collector: 998147a, 4 ноября 2026, 03:05:10 Europe/Samara.
- Commit workflow: b9c6d67, 4 ноября 2026, 03:09:00 Europe/Samara.
- Ветка: research/pandora-universal-30d-v1.
- Токены: ZEC, HYPE, NEAR, SOL, ENA, 1000PEPE, DOGE, SUI, AAVE, WLD.
- Данные: официальный public.bybit.com/trading, daily CSV.GZ, 4 октября —
  3 ноября 2026 (конец исключён), агрегация до минут.
- Исполнитель: GitHub Actions ubuntu-latest, matrix max-parallel 10.
- HTTP headers: только User-Agent. В исходном workflow нет Bybit secrets/env.
- Копии источников: universal_data.py.txt и pandora-universal-30d.yml.txt.

## Ключ Bybit

В этом сборщике Bybit API key не используется. В доступной истории также не
найдены имена/привязки Bybit key/secret или заголовки X-BAPI/signature. Это не
доказывает отсутствия ключа во внешнем secret store, старой машине или другом чате.
В текущих runtime bindings и именах переменных окружения Bybit-ключ не обнаружен.
Чтение только названий GitHub Actions secrets вернуло Forbidden; поэтому нельзя
утверждать, что в настройках репозитория ключа нет.

## Ещё один найденный документ

Из исторического ZIP blob 4007a3d восстановлен BYBIT_NETWORK_DIAGNOSIS.md. Он
описывает проверку publicTrade отдельно по десяти токенам, отмечает отсутствие
авторизации у public topics и тот же отказ CONNECT 403 со стороны прокси среды.
В нём штатное решение — применение сетевой конфигурации, а не ключ Bybit.

## Отдельная GitHub-аутентификация

В commit b76aa569 GH_TOKEN из github.token используется для Actions artifacts.
Это токен GitHub, а не подтверждение наличия Bybit API key. Его значения не
выводились. Новые рыночные файлы в ходе этого аудита не получены.
