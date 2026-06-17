# 單一容器：Ubuntu 24.04 同時跑 nginx（網站）+ python（訪客計數）
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx python3 python3-pip ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 發音評分用：faster-whisper（開源、免費、CPU 可跑）。建置時先下載模型，執行時免連網。
RUN pip3 install --break-system-packages --no-cache-dir faster-whisper
RUN python3 -c "from faster_whisper import WhisperModel; WhisperModel('base.en')"

# nginx 設定：預設 HTTPS(443，正式)；TEST_MODE=1 時改用 HTTP(80，本機測試免憑證)。
# 兩份設定先放著，啟動腳本依環境變數複製其中一份到 conf.d/app.conf。
RUN rm -f /etc/nginx/sites-enabled/default /etc/nginx/conf.d/default.conf
RUN cat > /etc/nginx/app-https.conf <<'EOF'
server {
    listen 443 ssl;
    server_name kyotozuiryu.com;
    ssl_certificate     /etc/letsencrypt/live/kyotozuiryu.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/kyotozuiryu.com/privkey.pem;
    root /var/www/html;
    index index.html;
    location /api/ { proxy_pass http://127.0.0.1:5000; }
    location / { try_files $uri $uri/ =404; }
}
EOF
RUN cat > /etc/nginx/app-http.conf <<'EOF'
server {
    listen 80;
    server_name _;
    root /var/www/html;
    index index.html;
    location /api/ { proxy_pass http://127.0.0.1:5000; }
    location / { try_files $uri $uri/ =404; }
}
EOF

# 啟動腳本：依 TEST_MODE 選 HTTP / HTTPS，背景跑後端、前景跑 nginx
RUN mkdir -p /app && cat > /app/start.sh <<'EOF'
#!/bin/sh
if [ "$TEST_MODE" = "1" ]; then
    echo "[start] TEST MODE -> HTTP on :80 (no certs)"
    cp /etc/nginx/app-http.conf /etc/nginx/conf.d/app.conf
else
    echo "[start] PROD -> HTTPS on :443"
    cp /etc/nginx/app-https.conf /etc/nginx/conf.d/app.conf
fi
python3 /app/server.py &
exec nginx -g 'daemon off;'
EOF
RUN chmod +x /app/start.sh

# 計數程式 + 網站內容
COPY server.py /app/server.py
COPY . /var/www/html/

EXPOSE 80 443
CMD ["sh", "/app/start.sh"]
