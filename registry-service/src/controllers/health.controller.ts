import { FastifyRequest, FastifyReply } from "fastify";
import * as chainService from "../services/chain.service.js";

/**
 * Controller = I/O. Liveness and chain-connectivity checks.
 */

export async function health(_request: FastifyRequest, reply: FastifyReply): Promise<void> {
  reply.send({ status: "ok" });
}

export async function chainStatus(
  _request: FastifyRequest,
  reply: FastifyReply
): Promise<void> {
  const status = await chainService.getChainStatus();
  reply.send(status);
}
