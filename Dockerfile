FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py risk.py engine_store.py entry_guards.py social_scrapers.py public_social.py momentum_scanner.py x_guest.py realtime_free.py x_list.py ./
RUN python -m py_compile app.py risk.py engine_store.py entry_guards.py social_scrapers.py public_social.py momentum_scanner.py x_guest.py realtime_free.py x_list.py
ENV PYTHONUNBUFFERED=1
CMD ["python","app.py"]
