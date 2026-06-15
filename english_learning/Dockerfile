# 單一容器：Ubuntu 24.04 同時跑 nginx（網站）+ python（訪客計數）
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx python3 python3-pip ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 發音評分用：faster-whisper（開源、免費、CPU 可跑）。建置時先下載模型，執行時免連網。
RUN pip3 install --break-system-packages --no-cache-dir faster-whisper
RUN python3 -c "from faster_whisper import WhisperModel; WhisperModel('base.en')"

# nginx 設定（內嵌）：只提供 HTTPS(443)，使用掛載的 Let's Encrypt 憑證
RUN rm -f /etc/nginx/sites-enabled/default
RUN cat > /etc/nginx/conf.d/app.conf <<'EOF'
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

# 計數程式 + 網站內容
COPY server.py /app/server.py
COPY . /var/www/html/

EXPOSE 443
# 背景跑計數程式，前景跑 nginx
CMD ["sh", "-c", "python3 /app/server.py & nginx -g 'daemon off;'"]
