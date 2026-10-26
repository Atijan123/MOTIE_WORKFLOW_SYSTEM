# Playwright, with only Chromium's headless shell: about a quarter of the size
# of Microsoft's all-browsers image. Run through docker-compose.yml's "e2e"
# service, which reaches the app as http://web:3000 on the Compose network.
FROM node:22-bookworm-slim
WORKDIR /e2e
COPY package.json package-lock.json ./
RUN npm ci \
 && npx playwright install --with-deps --only-shell chromium \
 && rm -rf /var/lib/apt/lists/* /root/.npm
CMD ["npx", "playwright", "test"]
