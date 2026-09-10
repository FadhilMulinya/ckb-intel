import { FastifyInstance } from "fastify";
import * as controller from "../controllers/registry.controller.js";

export async function registryRoutes(app: FastifyInstance) {
  app.get("/health", async () => ({ service: "CKB Wallet Behaviour Registry", version: "1.0.0", status: "ok" }));
  app.post("/wallets/analyze", controller.analyze);
  app.get("/wallets", controller.list);
  app.get("/wallets/:address", controller.get);
  app.get("/wallets/:address/behaviors", controller.behaviors);
  app.get("/wallets/:address/features", controller.features);
}
