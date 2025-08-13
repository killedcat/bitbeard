FROM nginx:alpine

RUN apk add --no-cache apache2-utils

COPY index.html /usr/share/nginx/html/index.html
COPY entrypoint.sh /entrypoint.sh
COPY default.conf /etc/nginx/conf.d/default.conf

RUN chmod +x /entrypoint.sh

# Inject configurable API base at build time
ARG API_BASE
ENV API_BASE=${API_BASE}
RUN if [ -n "$API_BASE" ]; then \
      sed -i "s|__API_BASE__|${API_BASE}|g" /usr/share/nginx/html/index.html; \
    else \
      sed -i 's|__API_BASE__|http://localhost:9870|g' /usr/share/nginx/html/index.html; \
    fi

ENTRYPOINT ["/entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
