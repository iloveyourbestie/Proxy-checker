FROM python:3.12-slim

WORKDIR /app

COPY bot.py /app/bot.py
COPY data /app/data

RUN pip install --no-cache-dir python-telegram-bot aiohttp

ENV PYTHONUNBUFFERED=1

CMD ["python", "bot.py"]
