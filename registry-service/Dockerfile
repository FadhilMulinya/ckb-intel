FROM node:22-slim

WORKDIR /app
COPY registry-service/package*.json ./
RUN npm ci --omit=dev
COPY registry-service/tsconfig.json ./
COPY registry-service/src ./src
RUN npx tsc

EXPOSE 3000
CMD ["node", "dist/index.js"]
