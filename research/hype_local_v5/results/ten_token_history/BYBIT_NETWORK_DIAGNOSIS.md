# Bybit WebSocket: диагностика

В текущей среде enforced restricted policy не разрешает stream.bybit.com. Исходный фактический запрос websocket-client завершился WebSocketProxyException: failed CONNECT via proxy status: 403. Handshake не произошёл, ACK и сделок нет. Повторная проверка текущей политики подтверждает отсутствие домена. Такой результат не доказывает блокировку со стороны Bybit или Render.

Черновик окружения сохранён с сохранением прежних разрешений: api.bybit.com, api.bytick.com, api.render.com, pandora-testnet-monitor-nfoc.onrender.com, stream.bybit.com; добавлен bybit-exchange.github.io для документации. Ответ платформы status=saved, requires_publish=true. Действующая среда по-прежнему spec_revision=1, домен не разрешён. Сохранение черновика не применяет разрешения.

Штатное исправление: в настройках этой облачной среды применить/опубликовать подготовленный сетевой черновик. После изменения политики выполнить:

    /workspace/pandora-testnet/.venv/bin/python /workspace/.pandora-setup/bybit_network_diagnostic.py

Проверка не использует базу, не запускает движок, не ставит ордера. Проверяет политику, handshake, subscription ACK, получение исполненных сделок отдельно по десяти токенам. Сохраняет штатный прокси и проверку TLS. Окно 15 секунд — только длительность диагностического наблюдения, не параметр стратегии. Нулевой поток редкого токена за короткое время сам по себе не доказывает ошибку подписки. Проверка завершает работу кодом 2 до сети, если домен явно запрещён.

Сверено с официальными источниками:

- https://bybit-exchange.github.io/docs/v5/ws/connect — USDT/USDC perpetual использует wss://stream.bybit.com/v5/public/linear; Public topics не требуют авторизации.
- https://bybit-exchange.github.io/docs/v5/websocket/public/trade — publicTrade.{symbol}; S означает сторону taker; реальные исполнения, не заявки стакана; несколько сообщений могут иметь одинаковый seq.
- https://bybit-exchange.github.io/docs/v5/rate-limit — не более 500 подключений за 5 минут, 1000 market-data подключений на IP отдельно для каждого класса рынка; HTTP 403 access too frequent имеет отдельный сценарий ожидания 10 минут.
- https://github.com/bybit-exchange/pybit/issues/326 — обсуждение предположения автора о WAF/User-Agent. Сопровождающий не воспроизвёл проблему, отверг маскировку браузера как надёжное решение и предложил проверить malformed request, banned IP, restricted regions, rate limits. Это не подтверждение причины нашей ошибки.

Официальный исходник документации прочитан из bybit-exchange/docs, commit ff8d45f2146ef97d7ec157ea46649920c885141c, docs/v5/websocket/wss-authentication.mdx, docs/v5/websocket/public/trade.mdx, docs/v5/rate-limit/rate-limit.mdx. Первоначальный предполагаемый путь docs/v5/ws/connect.mdx не существует; использован фактический файл с slug /v5/ws/connect.

После снятия запрета среды могут обнаружиться отдельные ограничения IP/региона Bybit или несовместимость прокси с Upgrade. Сейчас это не проверено. Не отключать прокси/TLS, не подменять географию и не менять URL на неофициальные зеркала. Render необходимо диагностировать отдельно на его фактическом исходящем IP; доступ к Render в текущем наборе инструментов отсутствует. PAPER использует реальные mainnet-данные и моделирует исполнение: переход на testnet не исправляет проблему достоверности mainnet-потока.
