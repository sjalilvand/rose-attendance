# Frontend / PWA image — template from docs/REQUIREMENTS.md section 21.
# Requires a React (Vite) project with package-lock.json and a build step.

FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:stable-alpine

COPY --from=build /app/dist /usr/share/nginx/html

# The gateway picks its nginx config at startup (see docker-entrypoint.sh):
#   deploy/tls/fullchain.pem + privkey.pem present → HTTPS (nginx.conf)
#   otherwise → plain HTTP (nginx-http.conf), e.g. local http://localhost/
COPY nginx.conf /etc/nginx/gateway-https.conf
COPY nginx-http.conf /etc/nginx/gateway-http.conf
COPY docker-entrypoint.sh /usr/local/bin/gateway-entrypoint.sh
RUN chmod +x /usr/local/bin/gateway-entrypoint.sh

ENTRYPOINT ["gateway-entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]

EXPOSE 80 443
