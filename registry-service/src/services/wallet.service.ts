import * as walletRepository from "../repositories/wallet.repository.js";
import { WalletDoc, WalletLabel } from "../db/models/Wallet.js";

/**
 * Service = logic. Read-side wallet queries + label write-back used by the
 * API layer.
 */

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

export async function getWallet(address: string): Promise<WalletDoc | null> {
  return walletRepository.findWalletByAddress(address);
}

export async function listWallets(
  page = 1,
  pageSize = 50,
  label?: WalletLabel
): Promise<Paginated<WalletDoc>> {
  const skip = (page - 1) * pageSize;
  const [items, total] = await Promise.all([
    walletRepository.listWallets(pageSize, skip, label),
    walletRepository.countWallets(label),
  ]);
  return { items, total, page, pageSize };
}

export interface UpdateWalletLabelInput {
  label: WalletLabel;
  botProbability?: number | null;
}

export async function updateWalletLabel(
  address: string,
  input: UpdateWalletLabelInput
): Promise<WalletDoc> {
  return walletRepository.updateLabel(address, {
    label: input.label,
    botProbability: input.botProbability ?? null,
    classifiedAt: new Date(),
  });
}
