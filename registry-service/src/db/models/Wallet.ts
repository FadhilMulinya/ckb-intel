import { Schema, model, Document } from "mongoose";

export interface WalletProfile extends Document {
  address: string;
  network: "mainnet";
  analysisVersion: "wallet-behaviour-v2";
  observation: Record<string, unknown>;
  evidence: Record<string, unknown>;
  featureSupport: Record<string, unknown>;
  features: Record<string, unknown>;
  behaviors: unknown[];
  limitations: string[];
  createdAt: Date;
  updatedAt: Date;
}

const WalletSchema = new Schema<WalletProfile>({
  address: { type: String, required: true, unique: true, index: true },
  network: { type: String, enum: ["mainnet"], required: true },
  analysisVersion: { type: String, enum: ["wallet-behaviour-v2"], required: true },
  observation: { type: Schema.Types.Mixed, required: true },
  evidence: { type: Schema.Types.Mixed, required: true },
  featureSupport: { type: Schema.Types.Mixed, required: true },
  features: { type: Schema.Types.Mixed, required: true },
  behaviors: { type: [Schema.Types.Mixed], required: true },
  limitations: { type: [String], required: true },
}, { timestamps: true });

export const Wallet = model<WalletProfile>("WalletBehaviourProfile", WalletSchema);
