# -------- Base image --------
FROM python:3.11-slim

# -------- Environment --------
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# -------- System deps --------
RUN apt-get update && apt-get install -y \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# -------- Workdir --------
WORKDIR /app

# -------- Install Python deps --------
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# -------- Copy project --------
COPY . .

# -------- Create data dirs (safe) --------
RUN mkdir -p data/results

# -------- Run bot --------
CMD ["python", "bot.py"]