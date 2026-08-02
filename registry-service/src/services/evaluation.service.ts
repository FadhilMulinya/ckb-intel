import { readFileSync, statSync } from "fs";
import { fileURLToPath } from "url";
import path from "path";
import { toHumanDate } from "../utils/humanDate.js";

/**
 * Service = logic. Reads the model evaluation artifact that
 * classifier-service/train_eval.py (Python) writes after each training run and
 * reshapes it into the API's response contract. This file is read live on
 * every request (not cached), so a fresh `train_eval.py` run is reflected
 * immediately without restarting this server.
 *
 * registry-service does not run the model itself -- this is read-only access to
 * an artifact the Python side produces, not a reimplementation of
 * anything in classifier-service/.
 */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// src/services -> src -> registry-service -> repo root -> classifier-service
const EVAL_RESULTS_PATH = path.resolve(
  __dirname,
  "../../../classifier-service/eval_results.json"
);

export interface EvaluationSummary {
  modelSelected: string;
  accuracy: number | null;
  precision: number | null;
  recall: number | null;
  f1Score: number | null;
  rocAuc: number | null;
  confusionMatrix: Record<string, number> | null;
  datasetStatistics: {
    nBotLike: number;
    nHumanLike: number;
    total: number;
    nShortHistoryRows: number;
    minTxFilterApplied: number;
  };
  labelDistribution: {
    bot: { count: number; pct: number };
    human: { count: number; pct: number };
  };
  cvModelComparison: unknown;
  featureImportance: unknown;
  labelProvenanceWarning: string | null;
  lastUpdatedAt: string;
}

export class EvaluationNotFoundError extends Error {}

export function getEvaluationSummary(): EvaluationSummary {
  let raw: string;
  let mtime: Date;
  try {
    raw = readFileSync(EVAL_RESULTS_PATH, "utf-8");
    mtime = statSync(EVAL_RESULTS_PATH).mtime;
  } catch {
    throw new EvaluationNotFoundError(
      `eval_results.json not found at ${EVAL_RESULTS_PATH} -- run classifier-service/train_eval.py first`
    );
  }

  const parsed = JSON.parse(raw);
  const heldOut = parsed.held_out_test_eval ?? {};
  const composition = parsed.training_composition ?? {};

  const nBotLike: number = composition.n_bot_like ?? 0;
  const nHumanLike: number = composition.n_human_like ?? 0;
  const total = nBotLike + nHumanLike;

  return {
    modelSelected: parsed.model_selected ?? null,
    accuracy: heldOut.accuracy ?? null,
    precision: heldOut.precision_bot ?? null,
    recall: heldOut.recall_bot ?? null,
    f1Score: heldOut.f1_bot ?? null,
    rocAuc: heldOut.roc_auc ?? null,
    confusionMatrix: heldOut.confusion_matrix ?? null,
    datasetStatistics: {
      nBotLike,
      nHumanLike,
      total,
      nShortHistoryRows: composition.n_short_history_rows ?? 0,
      minTxFilterApplied: composition.min_tx_filter_applied ?? 0,
    },
    labelDistribution: {
      bot: {
        count: nBotLike,
        pct: total > 0 ? Number(((nBotLike / total) * 100).toFixed(2)) : 0,
      },
      human: {
        count: nHumanLike,
        pct: total > 0 ? Number(((nHumanLike / total) * 100).toFixed(2)) : 0,
      },
    },
    cvModelComparison: parsed.cv_model_comparison ?? null,
    featureImportance: parsed.feature_importance ?? null,
    labelProvenanceWarning: parsed.label_provenance_warning ?? null,
    lastUpdatedAt: toHumanDate(mtime) ?? "unknown",
  };
}
