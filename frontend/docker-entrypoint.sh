#!/bin/sh
# Gateway auto-mode: choose the nginx config at container startup.
#   - TLS certificates mounted at /etc/nginx/tls → HTTPS variant
#   - otherwise → plain HTTP variant (local/test deployments)
set -e

if [ -f /etc/nginx/tls/fullchain.pem ] && [ -f /etc/nginx/tls/privkey.pem ]; then
    echo "gateway: TLS certificates found -> HTTPS mode"
    cp /etc/nginx/gateway-https.conf /etc/nginx/conf.d/default.conf
else
    echo "gateway: no TLS certificates -> HTTP mode (add deploy/tls/fullchain.pem + privkey.pem for HTTPS)"
    cp /etc/nginx/gateway-http.conf /etc/nginx/conf.d/default.conf
fi

exec "$@"
