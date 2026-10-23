# TLS certificates directory

Place the following files here (they are mounted read-only into the
`gateway` container at /etc/nginx/tls and are NEVER committed to Git):

- `fullchain.pem` — certificate chain
- `privkey.pem`   — private key

The gateway detects these files at startup: when both exist it serves
HTTPS (and redirects port 80); without them it falls back to plain HTTP
so local deployments work out of the box at http://localhost/.

Certificate renewal should be automated (e.g. certbot + reload hook,
then `docker compose restart gateway`).
