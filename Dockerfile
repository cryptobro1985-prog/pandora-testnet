FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY accounting.py market_data.py market_stream.py news_logic.py source_health.py whale_signals.py app.py risk.py engine_store.py entry_guards.py social_scrapers.py public_social.py momentum_scanner.py x_guest.py realtime_free.py x_list.py x_page.py piq_direct.py operator_cleanup.py restore_positions.py ./
RUN python -m py_compile accounting.py market_data.py market_stream.py news_logic.py source_health.py whale_signals.py app.py risk.py engine_store.py entry_guards.py social_scrapers.py public_social.py momentum_scanner.py x_guest.py realtime_free.py x_list.py x_page.py piq_direct.py operator_cleanup.py restore_positions.py
ENV PYTHONUNBUFFERED=1
CMD ["sh","-c","python operator_cleanup.py && python restore_positions.py && exec python app.py"]
