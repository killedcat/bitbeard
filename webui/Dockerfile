FROM nginx:alpine

RUN apk add --no-cache apache2-utils

COPY index.html /usr/share/nginx/html/index.html
COPY entrypoint.sh /entrypoint.sh
COPY default.conf /etc/nginx/conf.d/default.conf

RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
