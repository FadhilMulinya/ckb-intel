FROM node:22-slim AS build
WORKDIR /app
COPY registry-service/package*.json ./
RUN npm ci
COPY registry-service/tsconfig.json ./
COPY registry-service/src ./src
RUN npm run build

FROM node:22-slim
ENV NODE_ENV=production
WORKDIR /app
COPY registry-service/package*.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY --from=build /app/dist ./dist
USER node
EXPOSE 3000
CMD ["node", "dist/index.js"]
