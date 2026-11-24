FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 網站用普通用戶 app 執行，不用 root：即使網站被入侵，對方也不能修改系統檔案
RUN useradd --system --create-home --uid 1000 --shell /usr/sbin/nologin app

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app . .
# Windows 編輯後可能變成 CRLF，這裡轉回 LF 以免啟動失敗
RUN sed -i 's/\r$//' entrypoint.sh && chmod +x entrypoint.sh \
    && mkdir -p /app/staticfiles && chown -R app:app /app

USER app

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
