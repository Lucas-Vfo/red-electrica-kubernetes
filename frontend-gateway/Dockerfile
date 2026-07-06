FROM nginx:alpine

COPY index.html /usr/share/nginx/html/index.html

COPY styles.css /usr/share/nginx/html/styles.css

COPY app.js /usr/share/nginx/html/app.js

COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK \
    --interval=30s \
    --timeout=3s \
    --start-period=5s \
    --retries=3 \
    CMD wget \
        --quiet \
        --tries=1 \
        --spider \
        http://127.0.0.1/health \
        || exit 1