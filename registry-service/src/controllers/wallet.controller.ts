import { FastifyRequest, FastifyReply } from "fastify";
import * as walletService from "../services/wallet.service.js";
import { WALLET_LABELS, WalletLabel } from "../db/models/Wallet.js";

/**
 * Controller = I/O. Parses HTTP input, calls the service, shapes the HTTP
 * response. No business logic and no database access here.
 */

interface AddressParams {
  address: string;
}

interface PageQuery {
  page?: string;
  pageSize?: string;
  label?: string;
}

function parsePaging(query: PageQuery): { page: number; pageSize: number } {
  const page = Math.max(1, Number(query.page ?? 1) || 1);
  const pageSize = Math.min(200, Math.max(1, Number(query.pageSize ?? 50) || 50));
  return { page, pageSize };
}

function isWalletLabel(value: unknown): value is WalletLabel {
  return typeof value === "string" && (WALLET_LABELS as string[]).includes(value);
}

export async function listWallets(
  request: FastifyRequest<{ Querystring: PageQuery }>,
  reply: FastifyReply
): Promise<void> {
  const { page, pageSize } = parsePaging(request.query);
  const { label } = request.query;

  if (label !== undefined && !isWalletLabel(label)) {
    reply.code(400).send({
      error: `invalid label -- must be one of ${WALLET_LABELS.join(", ")}`,
      received: label,
    });
    return;
  }

  const result = await walletService.listWallets(page, pageSize, label);
  reply.send(result);
}

export async function getWallet(
  request: FastifyRequest<{ Params: AddressParams }>,
  reply: FastifyReply
): Promise<void> {
  const wallet = await walletService.getWallet(request.params.address);
  if (!wallet) {
    reply.code(404).send({ error: "wallet not found", address: request.params.address });
    return;
  }
  reply.send(wallet);
}

interface UpdateLabelBody {
  label?: string;
  botProbability?: number;
}

export async function updateLabel(
  request: FastifyRequest<{ Params: AddressParams; Body: UpdateLabelBody }>,
  reply: FastifyReply
): Promise<void> {
  const { label, botProbability } = request.body ?? {};

  if (!isWalletLabel(label)) {
    reply.code(400).send({
      error: `body.label is required and must be one of ${WALLET_LABELS.join(", ")}`,
      received: label,
    });
    return;
  }

  // No 404 path here on purpose -- the repository upserts, so a label can
  // arrive for an address registry-service has never ingested (see
  // wallet.repository.ts updateLabel's docstring).
  const wallet = await walletService.updateWalletLabel(request.params.address, {
    label,
    botProbability,
  });
  reply.send(wallet);
}
