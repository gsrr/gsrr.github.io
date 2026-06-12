# 單一容器：Ubuntu 24.04 同時跑 nginx（網站）+ python（訪客計數）
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx python3 \
    && rm -rf /var/lib/apt/lists/*

# nginx 設定（內嵌）：提供靜態網站，/api 轉給本機 python 計數程式
RUN rm -f /etc/nginx/sites-enabled/default
RUN cat > /etc/nginx/conf.d/app.conf <<'EOF'
server {
    listen 80;
    server_name _;
    root /var/www/html;
    index index.html;
    location /api/ { proxy_pass http://127.0.0.1:5000; }
    location / { try_files $uri $uri/ =404; }
}
EOF

# 計數程式 + 網站內容
COPY server.py /app/server.py
COPY . /var/www/html/

EXPOSE 80
# 背景跑計數程式，前景跑 nginx
CMD ["sh", "-c", "python3 /app/server.py & nginx -g 'daemon off;'"]
