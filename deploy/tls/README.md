# TLS certificates directory

Place the following files here (they are mounted read-only into the
`gateway` container at /etc/nginx/tls and are NEVER committed to Git):

- `fullchain.pem` — certificate chain
- `privkey.pem`   — private key

Certificate renewal should be automated (e.g. certbot + reload hook).
