# The Next.js frontend. Two images from one file:
#   target "dev"  - `next dev`, source bind-mounted by docker-compose.yml
#   target "prod" - a built, self-contained server (`docker build --target prod`)
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# Exactly the versions in package-lock.json, nothing newer.
RUN npm ci

FROM deps AS dev
ENV NEXT_TELEMETRY_DISABLED=1
CMD ["npm", "run", "dev"]

# The typecheck and unit tests, as a build step (CI's frontend job:
# `docker build --target check frontend`), so CI needs no Node on the host.
FROM deps AS check
COPY . .
RUN npm run typecheck && npm test

FROM deps AS build
ENV NEXT_TELEMETRY_DISABLED=1
# Which app to build (step 12b): next.config.mjs picks its pages by PORTAL.
ARG PORTAL=applicant
ENV PORTAL=${PORTAL}
COPY . .
RUN npm run build

FROM node:22-alpine AS prod
WORKDIR /app
ARG PORTAL=applicant
# HOSTNAME: listen on every address in the container (Docker sets HOSTNAME to
# the container's id, which Next's server would otherwise bind to).
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORTAL=${PORTAL} HOSTNAME=0.0.0.0 PORT=3000
# The standalone output carries only the files the server needs.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
# Icons, the service worker and the offline page (step 12h).
COPY --from=build /app/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
