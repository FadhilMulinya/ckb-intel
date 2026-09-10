import axios from "axios";
import { config } from "../config/index.js";
import * as repository from "../repositories/wallet.repository.js";
import { ContractError, validateProfile } from "../contract/profile.js";
import { validateCkbAddress } from "../ckbaddressvalidator.js";

export class RegistryError extends Error {
  constructor(public status: string, message: string, public statusCode: number, public details?: unknown) { super(message); }
}

export async function analyze(address: string, mode = "frozen") {
  if (!(await validateCkbAddress(address))) throw new RegistryError("INVALID_ADDRESS", "invalid mainnet CKB address", 400);
  let profile: Record<string, any>;
  try {
    const response = await axios.post(`${config.classifierServiceUrl}/analyze`, { address, mode }, { timeout: config.classifierTimeoutMs });
    profile = await validateProfile(response.data);
  } catch (error) {
    if (error instanceof ContractError) throw new RegistryError(error.status, error.message, 422);
    if (axios.isAxiosError(error)) {
      const detail = error.response?.data?.detail;
      const status = typeof detail === "object" && detail?.status ? detail.status : undefined;
      const message = typeof detail === "object" && detail?.message ? detail.message : (typeof detail === "string" ? detail : error.message);
      const code = status === "INVALID_ADDRESS" ? 400 : ["NOT_IN_FROZEN_DATASET", "V2_LIVE_ANALYSIS_NOT_YET_SUPPORTED", "COLLECTION_FAILED"].includes(status ?? "") ? 422 : error.response?.status && error.response.status >= 500 ? 502 : 503;
      if (status) throw new RegistryError(status, message, code, detail);
      throw new RegistryError("CLASSIFIER_SERVICE_UNAVAILABLE", message, 503);
    }
    throw error;
  }
  const saved = await repository.upsert(profile);
  return { ...profile, created_at: saved.createdAt, updated_at: saved.updatedAt };
}

export { repository };
