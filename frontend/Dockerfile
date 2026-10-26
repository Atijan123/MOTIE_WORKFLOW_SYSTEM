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

FROM deps AS build
ENV NEXT_TELEMETRY_DISABLED=1
COPY . .
RUN npm run build

FROM node:22-alpine AS prod
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
# The standalone output carries only the files the server needs.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
