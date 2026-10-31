# ─────────────────────────────────────────────────────────────
# GEMA MX — Web App  (Nginx estático)
# Sirve la app desde /usr/share/nginx/html.
# Los datos vivos se montan desde results/data/ del host.
# ─────────────────────────────────────────────────────────────
FROM nginx:1.27-alpine

# Copiar la app estática
COPY index.html  /usr/share/nginx/html/
COPY favicon.svg /usr/share/nginx/html/
COPY css/        /usr/share/nginx/html/css/
COPY js/         /usr/share/nginx/html/js/

# Configuración personalizada de Nginx
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://localhost/health || exit 1
