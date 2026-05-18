# Официальный образ Playwright с предустановленным Chromium и системными
# библиотеками. ВАЖНО: версия здесь должна совпадать с playwright в
# requirements.txt — иначе python-пакет ищет браузер не там, где он лежит
# в образе ('Executable doesn't exist at /ms-playwright/chromium_*').
FROM mcr.microsoft.com/playwright/python:v1.60.0-jammy

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Зависимости отдельным слоем — кешируем
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Исходники
COPY bot/ ./bot/

# Каталог для SQLite и storage_state.json. На Railway сюда монтируется Volume.
RUN mkdir -p /data
ENV DATA_DIR=/data

CMD ["python", "-m", "bot.main"]
