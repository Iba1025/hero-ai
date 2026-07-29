# syntax=docker/dockerfile:1
# Hero.AI edge image (Phase 6, DEC-27): Caddy serving the built SPA +
# reverse-proxying API paths to the api container.
#
# API ORIGIN: nothing is baked at build time. Every SPA API call is a
# same-origin relative path (web/src/api.ts `fetch(path)`), so the API origin
# is wherever this Caddy is reached — localhost for the local loop, the pilot
# domain in production. Origin/TLS are runtime concerns of the Caddyfile
# (SITE_ADDRESS env), never a rebuild.

FROM node:22-alpine AS build

WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build


FROM caddy:2-alpine

COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /web/dist /srv
