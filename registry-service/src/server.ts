import Fastify, { FastifyInstance } from "fastify";
import fastifySwagger from "@fastify/swagger";
import { config } from "./config/index.js";
import { connectMongo, disconnectMongo } from "./db/mongo.js";
import { registryRoutes } from "./routes/index.js";
import { registerDocs } from "./docs.js";

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

  app.register(fastifySwagger, {
    openapi: {
      info: {
        title: "CKB Wallet Behaviour Registry",
        version: "1.0.0",
        description: "Descriptive wallet-behaviour profiles produced by classifier-service.",
      },
      tags: [{ name: "Registry" }],
    },
  });
  app.register(registryRoutes, { prefix: "/api/v1" });
  registerDocs(app);

  return app;
}

export async function startServer(): Promise<void> {
  // Refuse to start unless every external API (CKB RPC via CCC, Explorer API)
  // is reachable — a server whose dependencies are down would only serve errors.
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
