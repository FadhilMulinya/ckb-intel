import { FastifyInstance } from "fastify";
import * as walletController from "../../controllers/wallet.controller.js";
import * as ingestionController from "../../controllers/ingestion.controller.js";
import * as healthController from "../../controllers/health.controller.js";
import * as evaluationController from "../../controllers/evaluation.controller.js";
import { registerDocs } from "../../docs.js";

/**
 * v1 route registrations. Mounted under /api/v1 by the server.
 * A future breaking change gets a routes/v2 folder and its own prefix —
 * existing consumers keep working.
 */
export async function v1Routes(app: FastifyInstance): Promise<void> {
  app.get("/health", healthController.health);
  app.get("/chain/status", healthController.chainStatus);

  app.get("/wallets", walletController.listWallets);
  app.get("/wallets/:address", walletController.getWallet);
  app.patch("/wallets/:address/label", walletController.updateLabel);

  app.post("/ingest", ingestionController.ingestWallets);

  app.get("/model/evaluation", evaluationController.getEvaluation);

  registerDocs(app); // GET /api/v1/docs (Scalar), GET /api/v1/openapi.json
}
