import { FastifyInstance } from "fastify";
import { environments } from "../environments.js";
import { validateCkbAddress } from "../ckbaddressvalidator.js";
import * as controller from "../controllers/registry.controller.js";

export async function registryRoutes(app: FastifyInstance) {
  // Reuse one limiter across all read routes, with a separate analysis store.
  const readLimit = app.rateLimit({ max: environments.readRateLimit, timeWindow: environments.readRateWindowMs });
  const analyzeLimit = app.rateLimit({ max: environments.analyzeRateLimit, timeWindow: environments.analyzeRateWindowMs });
  app.addHook("preHandler", async (request, reply) => {
    const address = (request.params as { address?: string })?.address;
    if (address !== undefined && !(await validateCkbAddress(address))) {
      return reply.code(400).send({ status: "INVALID_ADDRESS", message: "invalid mainnet CKB address" });
    }
  });
  app.get("/health", { schema: { tags: ["Registry"], summary: "Health check" } }, async () => ({ service: "CKB Wallet Behaviour Registry", version: "1.0.0", status: "ok" }));
  app.post<{ Body: { address?: string; mode?: string } }>("/wallets/analyze", { onRequest: analyzeLimit, schema: { tags: ["Registry"], summary: "Analyze and register a wallet", body: { type: "object", required: ["address"], properties: { address: { type: "string", minLength: 1, maxLength: 2048 }, mode: { type: "string", enum: ["frozen", "live"], default: "frozen" } } } } }, controller.analyze);
  app.get<{ Querystring: { page?: string; pageSize?: string } }>("/wallets", { onRequest: readLimit, schema: { tags: ["Registry"], summary: "List registered wallet profiles", querystring: { type: "object", properties: { page: { type: "string", pattern: "^[1-9][0-9]{0,8}$" }, pageSize: { type: "string", pattern: "^[1-9][0-9]{0,2}$" } } } } }, controller.list);
  app.get<{ Params: { address: string } }>("/wallets/:address", { onRequest: readLimit, schema: { tags: ["Registry"], summary: "Get the latest wallet profile", params: { type: "object", required: ["address"], properties: { address: { type: "string", minLength: 1, maxLength: 2048 } } } } }, controller.get);
  app.get<{ Params: { address: string } }>("/wallets/:address/behaviors", { onRequest: readLimit, schema: { tags: ["Registry"], summary: "Get descriptive behavior results", params: { type: "object", required: ["address"], properties: { address: { type: "string", minLength: 1, maxLength: 2048 } } } } }, controller.behaviors);
  app.get<{ Params: { address: string } }>("/wallets/:address/features", { onRequest: readLimit, schema: { tags: ["Registry"], summary: "Get features and support states", params: { type: "object", required: ["address"], properties: { address: { type: "string", minLength: 1, maxLength: 2048 } } } } }, controller.features);
}
