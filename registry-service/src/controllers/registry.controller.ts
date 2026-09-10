import { FastifyReply, FastifyRequest } from "fastify";
import * as service from "../services/registry.service.js";
import { response } from "../repositories/wallet.repository.js";

export async function analyze(request: FastifyRequest<{ Body: { address?: string; mode?: string } }>, reply: FastifyReply) {
  if (typeof request.body?.address !== "string") return reply.code(400).send({ status: "INVALID_ADDRESS", message: "address is required" });
  if (request.body.mode !== undefined && request.body.mode !== "frozen" && request.body.mode !== "live") return reply.code(400).send({ status: "INVALID_MODE", message: "mode must be frozen or live" });
  try { return reply.send(await service.analyze(request.body.address, request.body.mode ?? "frozen")); }
  catch (error) {
    if (error instanceof service.RegistryError) return reply.code(error.statusCode).send({ status: error.status, message: error.message, ...(error.details && typeof error.details === "object" ? { details: error.details } : {}) });
    return reply.code(500).send({ status: "REGISTRY_INTERNAL_ERROR", message: (error as Error).message });
  }
}

export async function get(request: FastifyRequest<{ Params: { address: string } }>, reply: FastifyReply) {
  const value = await service.repository.find(request.params.address);
  return value ? reply.send(response(value)) : reply.code(404).send({ status: "REGISTRY_RECORD_NOT_FOUND" });
}

export async function behaviors(request: FastifyRequest<{ Params: { address: string } }>, reply: FastifyReply) {
  const value = await service.repository.find(request.params.address);
  return value ? reply.send({ address: value.address, version: value.analysisVersion, behaviors: value.behaviors }) : reply.code(404).send({ status: "REGISTRY_RECORD_NOT_FOUND" });
}

export async function features(request: FastifyRequest<{ Params: { address: string } }>, reply: FastifyReply) {
  const value = await service.repository.find(request.params.address);
  return value ? reply.send({ address: value.address, version: value.analysisVersion, feature_support: value.featureSupport, features: value.features }) : reply.code(404).send({ status: "REGISTRY_RECORD_NOT_FOUND" });
}

export async function list(request: FastifyRequest<{ Querystring: { page?: string; pageSize?: string } }>, reply: FastifyReply) {
  const page = Math.max(1, Number(request.query.page ?? 1) || 1); const pageSize = Math.min(200, Math.max(1, Number(request.query.pageSize ?? 50) || 50));
  const result = await service.repository.list((page - 1) * pageSize, pageSize);
  return reply.send({ items: result.items.map(response), total: result.total, page, pageSize });
}
