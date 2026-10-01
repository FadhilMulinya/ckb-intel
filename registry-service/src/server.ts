import Fastify, { FastifyInstance, FastifyError } from "fastify";
import fastifySwagger from "@fastify/swagger";
import cors from "@fastify/cors";
import rateLimit from "@fastify/rate-limit";
import { environments } from "./environments.js";
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
  const app = Fastify({ logger: true, bodyLimit: 16384,
    trustProxy: environments.trustedProxies.length ? environments.trustedProxies : false });

  app.setErrorHandler<FastifyError>((error, request, reply) => {
    const statusCode = error.statusCode ?? 500;
    if (statusCode >= 500) {
      request.log.error({ err: error }, "request failed");
      return reply.code(500).send({ status: "REGISTRY_INTERNAL_ERROR", message: "Internal server error" });
    }
    return reply.code(statusCode).send(error);
  });
  app.register(cors, {
    origin: environments.corsAllowedOrigins,
    methods: ["GET", "POST", "OPTIONS"],
    allowedHeaders: ["Content-Type", "Accept"],
    exposedHeaders: ["Retry-After", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
    credentials: false,
  });
  app.register(rateLimit, { global: false, max: environments.readRateLimit,
    timeWindow: environments.readRateWindowMs, cache: 10000 });

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
  // Initial database connectivity is required; health thereafter is liveness.
  await connectMongo();

  const app = buildApp();
  await app.listen({ port: environments.apiPort, host: environments.apiHost });

  const shutdown = async (signal: string) => {
    app.log.info(`received ${signal}, shutting down`);
    await app.close();
    await disconnectMongo();
    process.exit(0);
  };
  process.on("SIGINT", () => void shutdown("SIGINT"));
  process.on("SIGTERM", () => void shutdown("SIGTERM"));
}
