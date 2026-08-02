import Fastify, { FastifyInstance } from "fastify";
import { config } from "./config/index.js";
import { connectMongo, disconnectMongo } from "./db/mongo.js";
import { v1Routes } from "./routes/v1/index.js";
import { assertExternalDependenciesAlive } from "./services/preflight.service.js";

/**
 * All server wiring lives here so the entrypoint (index.ts) stays clean:
 *  - buildApp(): constructs the Fastify instance and mounts versioned routes.
 *    Exported separately so tests can spin up the app with app.inject()
 *    without opening a port or touching the network.
 *  - startServer(): connects the database, starts listening, and installs
 *    graceful shutdown handlers.
 */

export function buildApp(): FastifyInstance {
  const app = Fastify({ logger: true });

  app.register(v1Routes, { prefix: "/api/v1" });
  // Future breaking API changes: app.register(v2Routes, { prefix: "/api/v2" });

  return app;
}

export async function startServer(): Promise<void> {
  // Refuse to start unless every external API (CKB RPC via CCC, Explorer API)
  // is reachable — a server whose dependencies are down would only serve errors.
  await assertExternalDependenciesAlive();

  await connectMongo();

  const app = buildApp();
  await app.listen({ port: config.apiPort, host: config.apiHost });

  const shutdown = async (signal: string) => {
    app.log.info(`received ${signal}, shutting down`);
    await app.close();
    await disconnectMongo();
    process.exit(0);
  };
  process.on("SIGINT", () => void shutdown("SIGINT"));
  process.on("SIGTERM", () => void shutdown("SIGTERM"));
}
