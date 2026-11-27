FROM nginx:1.27.5-alpine

ENV EXPOSE_API_DOCS=1

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY frontend/docs-access.sh /docker-entrypoint.d/10-docs-access.sh
COPY frontend/index.html frontend/app.js frontend/style.css /usr/share/nginx/html/

RUN chmod +x /docker-entrypoint.d/10-docs-access.sh

EXPOSE 80
