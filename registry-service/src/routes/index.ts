import { FastifyInstance } from "fastify";
import * as controller from "../controllers/registry.controller.js";

export async function registryRoutes(app: FastifyInstance) {
  app.get("/health", { schema: { tags: ["Registry"], summary: "Health check" } }, async () => ({ service: "CKB Wallet Behaviour Registry", version: "1.0.0", status: "ok" }));
  app.post("/wallets/analyze", { schema: { tags: ["Registry"], summary: "Analyze and register a wallet", body: { type: "object", required: ["address"], properties: { address: { type: "string" }, mode: { type: "string", enum: ["frozen", "live"], default: "frozen" } } } } }, controller.analyze);
  app.get("/wallets", { schema: { tags: ["Registry"], summary: "List registered wallet profiles", querystring: { type: "object", properties: { page: { type: "string" }, pageSize: { type: "string" } } } } }, controller.list);
  app.get("/wallets/:address", { schema: { tags: ["Registry"], summary: "Get the latest wallet profile", params: { type: "object", required: ["address"], properties: { address: { type: "string" } } } } }, controller.get);
  app.get("/wallets/:address/behaviors", { schema: { tags: ["Registry"], summary: "Get descriptive behavior results", params: { type: "object", required: ["address"], properties: { address: { type: "string" } } } } }, controller.behaviors);
  app.get("/wallets/:address/features", { schema: { tags: ["Registry"], summary: "Get features and support states", params: { type: "object", required: ["address"], properties: { address: { type: "string" } } } } }, controller.features);
}
