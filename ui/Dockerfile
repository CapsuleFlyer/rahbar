FROM nginxinc/nginx-unprivileged:1.31-alpine3.24
USER root
RUN apk upgrade --no-cache \
    && apk info -v libxml2
COPY nginx.conf /etc/nginx/nginx.conf
COPY index.html /usr/share/nginx/html/index.html
USER 101
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
