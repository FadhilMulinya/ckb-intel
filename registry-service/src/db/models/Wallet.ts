import { Schema, model, Document } from "mongoose";
import { toHumanDate } from "../../utils/humanDate.js";

// Mirrors classifier-service/predict.py's classify() `verdict` field exactly
// (classifier-service/predict.py: verdict = "bot" | "human" | "uncertain" | "unknown")
// -- no values exist here that Python doesn't also produce.
export type WalletLabel = "bot" | "human" | "uncertain" | "unknown";
export const WALLET_LABELS: WalletLabel[] = ["bot", "human", "uncertain", "unknown"];

export interface WalletDoc extends Document {
  address: string;
  // Identity fields are resolved by POST /ingest (via CCC). Not required at
  // the schema level: PATCH /wallets/:address/label can create a wallet
  // record before ingestion has ever run for that address (see
  // wallet.repository.ts updateLabel's upsert), so these may be briefly
  // unset until/unless ingestion fills them in.
  lockScriptHash?: string;
  network?: "mainnet"; // mainnet only, see config/index.ts
  firstSeenMs?: number;
  lastSeenMs?: number;
  txCount: number;
  // Classification result written back by classifier-service/predict.py after it
  // scores a wallet. label/botProbability are exactly Python's output;
  // classifiedAt is Node-generated storage metadata (when this record was
  // last written), not something Python returns.
  label?: WalletLabel | null;
  botProbability?: number | null;
  classifiedAt?: Date | null;
  ingestionStatus: "pending" | "in_progress" | "complete" | "failed";
  lastIngestedAt?: Date;
  createdAt: Date;
  updatedAt: Date;
}

const WalletSchema = new Schema<WalletDoc>(
  {
    address: { type: String, required: true, unique: true, index: true },
    lockScriptHash: { type: String, index: true },
    network: { type: String, enum: ["mainnet"] },
    firstSeenMs: { type: Number },
    lastSeenMs: { type: Number },
    txCount: { type: Number, default: 0 },
    label: { type: String, enum: [...WALLET_LABELS, null], default: null, index: true },
    botProbability: { type: Number, default: null },
    classifiedAt: { type: Date, default: null },
    ingestionStatus: {
      type: String,
      enum: ["pending", "in_progress", "complete", "failed"],
      default: "pending",
    },
    lastIngestedAt: { type: Date },
  },
  {
    timestamps: true,
    // API responses show human-readable dates ("Aug 2, 2026, 8:39 AM UTC"),
    // not raw ISO-8601 -- storage in Mongo (real Date objects) is untouched,
    // this only rewrites the JSON sent over HTTP (reply.send() serializes
    // documents via this transform).
    toJSON: {
      // `ret` is the plain JSON representation being built, not the typed
      // document (WalletDoc's fields are real Date objects) -- it's
      // reassigned to human-readable strings here, so it's typed loosely
      // on purpose.
      transform(_doc, ret: Record<string, unknown>) {
        ret.createdAt = toHumanDate(ret.createdAt as Date);
        ret.updatedAt = toHumanDate(ret.updatedAt as Date);
        ret.classifiedAt = toHumanDate(ret.classifiedAt as Date | null);
        ret.lastIngestedAt = toHumanDate(ret.lastIngestedAt as Date | undefined);
        return ret;
      },
    },
  }
);

export const Wallet = model<WalletDoc>("Wallet", WalletSchema);
