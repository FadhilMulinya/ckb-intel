import axios, { AxiosInstance } from "axios";
import { config } from "../config/index.js";

/**
 * Raw shapes returned by the CKB Explorer API (JSON:API style).
 * Only the fields we actually use are typed here — the API returns more.
 * Ref: https://ckb-explorer.readme.io/reference/transactions-of-an-address
 */
export interface ExplorerDisplayInput {
  id: string;
  from_cellbase: boolean;
  capacity: string; // "" for cellbase inputs
  address_hash: string; // "" for cellbase inputs
  target_block_number?: string;
  generated_tx_hash?: string;
}

export interface ExplorerDisplayOutput {
  id: string;
  capacity: string;
  address_hash: string;
  status: string; // "live" | "dead"
  consumed_tx_hash?: string;
}

export interface ExplorerTxAttributes {
  is_cellbase: boolean;
  transaction_hash: string;
  block_number: string;
  block_timestamp: string; // epoch ms, as a string
  display_inputs_count: number;
  display_outputs_count: number;
  display_inputs: ExplorerDisplayInput[];
  display_outputs: ExplorerDisplayOutput[];
  income: string; // net capacity change for the queried address, in Shannon
}

export interface ExplorerTxEntry {
  id: string;
  type: string;
  attributes: ExplorerTxAttributes;
}

export interface ExplorerListResponse<T> {
  data: T[];
  meta: { total: number; page_size: number };
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export class ExplorerClient {
  private http: AxiosInstance;

  constructor(baseUrl: string = config.explorerApiUrl) {
    this.http = axios.create({
      baseURL: baseUrl,
      headers: {
        Accept: "application/vnd.api+json",
        "Content-Type": "application/vnd.api+json",
      },
      timeout: 15_000,
    });
  }

  /**
   * Liveness probe used by the startup pre-flight check. Hits the cheap
   * statistics endpoint; any 2xx response means the Explorer API is reachable
   * and serving. Throws (axios error) otherwise.
   */
  async ping(): Promise<void> {
    await this.http.get("/statistics/tip_block_number", { timeout: 10_000 });
  }

  /** Fetch a single page of an address's transaction history. */
  async getAddressTransactionsPage(
    address: string,
    page: number,
    pageSize: number = config.explorerPageSize,
    sort: "time.asc" | "time.desc" = "time.asc"
  ): Promise<ExplorerListResponse<ExplorerTxEntry>> {
    const { data } = await this.http.get<ExplorerListResponse<ExplorerTxEntry>>(
      `/address_transactions/${address}`,
      { params: { page, page_size: pageSize, sort } }
    );
    return data;
  }

  /**
   * Async generator that pages through an address's transactions in the
   * given order, yielding one entry at a time. Stops once `maxTx` is reached
   * (safety cap) or the API is exhausted. Callers may also just stop
   * consuming early (e.g. the ingestion service breaks out once it pages
   * past the training time window) — no further requests are made.
   */
  async *iterateAddressTransactions(
    address: string,
    maxTx: number = config.maxTxPerWallet,
    sort: "time.asc" | "time.desc" = "time.desc"
  ): AsyncGenerator<ExplorerTxEntry> {
    let page = 1;
    let yielded = 0;
    const pageSize = config.explorerPageSize;

    while (yielded < maxTx) {
      const response = await this.getAddressTransactionsPage(
        address,
        page,
        pageSize,
        sort
      );

      if (!response.data || response.data.length === 0) {
        return;
      }

      for (const entry of response.data) {
        yield entry;
        yielded += 1;
        if (yielded >= maxTx) return;
      }

      const totalPages = Math.ceil(response.meta.total / pageSize);
      if (page >= totalPages) return;

      page += 1;
      await sleep(config.requestDelayMs);
    }
  }
}

export const explorerClient = new ExplorerClient();
