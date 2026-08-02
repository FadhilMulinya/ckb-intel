import { FastifyRequest, FastifyReply } from "fastify";
import * as ingestionService from "../services/ingestion.service.js";

/**
 * Controller = I/O. Accepts ingestion requests over HTTP and delegates to
 * the ingestion service.
 */

interface IngestBody {
  addresses?: string[];
}

export async function ingestWallets(
  request: FastifyRequest<{ Body: IngestBody }>,
  reply: FastifyReply
): Promise<void> {
  const addresses = request.body?.addresses;
  if (!Array.isArray(addresses) || addresses.length === 0) {
    reply.code(400).send({ error: "body must be { addresses: string[] } with at least one address" });
    return;
  }

  const results = await ingestionService.ingestWallets(addresses);
  reply.send({ requested: addresses.length, results });
}
