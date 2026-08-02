import { config } from "../config/index.js";

/**
 * Service = logic. The single place where the ingestion time window is
 * defined and reasoned about. Nothing else in the codebase does date math —
 * ingestion asks this file "is this timestamp in scope?".
 *
 * Why a window at all: bots/exchange wallets can have enormous full
 * histories. The model is trained on ONE YEAR of activity
 * (default: 2025-06-01 → 2026-06-30, configurable via env), so ingestion
 * only stores — and only pages far enough to cover — that window.
 *
 * The Explorer API has no server-side time filter (verified: only
 * page/page_size/sort). So the strategy is: page newest-first
 * (sort=time.desc), skip transactions after the window, store transactions
 * inside it, and stop paging at the first transaction before it.
 */

export interface TimeWindow {
  startMs: number; // inclusive
  endMs: number; // inclusive
}

export function getIngestionWindow(): TimeWindow {
  const startMs = Date.parse(config.ingestWindowStart);
  const endMs = Date.parse(config.ingestWindowEnd);
  if (Number.isNaN(startMs) || Number.isNaN(endMs)) {
    throw new Error(
      `Invalid INGEST_WINDOW_START/INGEST_WINDOW_END — must be ISO dates, got ` +
        `"${config.ingestWindowStart}" / "${config.ingestWindowEnd}"`
    );
  }
  if (startMs >= endMs) {
    throw new Error("INGEST_WINDOW_START must be before INGEST_WINDOW_END");
  }
  return { startMs, endMs };
}

/** Transaction falls inside the training window — store it. */
export function isWithinWindow(timestampMs: number, window: TimeWindow): boolean {
  return timestampMs >= window.startMs && timestampMs <= window.endMs;
}

/** Transaction is newer than the window — skip it, keep paging (desc order). */
export function isAfterWindow(timestampMs: number, window: TimeWindow): boolean {
  return timestampMs > window.endMs;
}

/**
 * Transaction is older than the window — when paging newest-first,
 * everything after this is older still: stop paging entirely.
 */
export function isBeforeWindow(timestampMs: number, window: TimeWindow): boolean {
  return timestampMs < window.startMs;
}

export function describeWindow(window: TimeWindow): string {
  const iso = (ms: number) => new Date(ms).toISOString().slice(0, 10);
  return `${iso(window.startMs)} → ${iso(window.endMs)}`;
}
