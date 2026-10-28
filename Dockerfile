FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY strategy1_week_backtest.py strategy1_universal_optimizer.py strategy1_algo_footprints.py strategy1_algo_12h_compare.py local_order_flow.py local_caterpillar.py strategy_stats.py hyperdata_runner.py hyperliquid_transport.py emergency_guard.py liquidation_stream.py operator_requests.json accounting.py learning_audit.py market_data.py market_stream.py news_logic.py source_health.py whale_signals.py hype_h1_swing.py app.py risk.py engine_store.py entry_guards.py social_scrapers.py public_social.py momentum_scanner.py x_guest.py realtime_free.py x_list.py x_page.py piq_direct.py operator_cleanup.py restore_positions.py ./
RUN python -m py_compile strategy1_week_backtest.py strategy1_universal_optimizer.py strategy1_algo_footprints.py strategy1_algo_12h_compare.py local_order_flow.py local_caterpillar.py strategy_stats.py hyperdata_runner.py hyperliquid_transport.py emergency_guard.py liquidation_stream.py accounting.py learning_audit.py market_data.py market_stream.py news_logic.py source_health.py whale_signals.py hype_h1_swing.py app.py risk.py engine_store.py entry_guards.py social_scrapers.py public_social.py momentum_scanner.py x_guest.py realtime_free.py x_list.py x_page.py piq_direct.py operator_cleanup.py restore_positions.py
ENV PYTHONUNBUFFERED=1
CMD ["python","app.py"]
