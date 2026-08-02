import { config } from "./config/index.js";

/**
 * Hand-authored OpenAPI 3.0 document for the public API surface under
 * /api/v1. Kept as a plain object (not generated from Fastify route
 * schemas) so adding this didn't require retrofitting schema validation
 * onto every existing route -- it's the source of truth for src/docs.ts's
 * /openapi.json + Scalar /docs page. Keep this in sync when routes/v1
 * changes shape: every route in that file should have a matching entry
 * here, with a full `description` (not just a one-line `summary`), a
 * worked `example` on every schema, and every response status code the
 * controller can actually send documented -- not just the happy path.
 */
export function buildOpenApiDocument() {
  const EXAMPLE_ADDRESS =
    "ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsq2hhwwfmxw3e2v6wya8kjw4wc7vlz9jqmgfk8t3y";
  const EXAMPLE_DATE = "Aug 2, 2026, 8:39 AM UTC";

  const walletLabel = {
    type: "string",
    enum: ["bot", "human", "uncertain", "unknown"],
    description:
      "Mirrors classifier-service/predict.py's `verdict` field exactly, value for value:\n" +
      "- `bot` — model scored this address as automated/bot-operated behavior.\n" +
      "- `human` — model scored this address as human-operated behavior.\n" +
      "- `uncertain` — the model's confidence fell inside its calibrated uncertain band; not a confident call either way, route to manual review.\n" +
      "- `unknown` — not enough transaction history existed to extract behavioral features at all.\n" +
      "No other values exist. This enum is defined here to match what the Python classifier produces, not the other way around.",
    example: "bot",
  };

  const humanDateField = (label: string) => ({
    type: "string",
    nullable: true,
    description: `${label} Formatted human-readable (e.g. "${EXAMPLE_DATE}"), not raw ISO-8601 -- storage in MongoDB is real Date objects, this is a display-only transform applied when the document is serialized to JSON.`,
    example: EXAMPLE_DATE,
  });

  const wallet = {
    type: "object",
    description:
      "A single wallet's identity + classification record -- the only kind of document this service stores. Identity fields (lockScriptHash, network, firstSeenMs, lastSeenMs) are populated by POST /ingest; classification fields (label, botProbability, classifiedAt) are populated by PATCH /wallets/{address}/label. A wallet can legitimately have only one half populated (e.g. labeled before it was ever ingested) -- see the auto-create note on PATCH below.",
    properties: {
      address: {
        type: "string",
        description: "The CKB address this record is keyed on (mainnet only). Unique.",
        example: EXAMPLE_ADDRESS,
      },
      lockScriptHash: {
        type: "string",
        nullable: true,
        description:
          "The address's canonical lock script hash, resolved via CCC during ingestion. This, not the address string, is the true wallet identity key -- one wallet can technically be represented by more than one address string. Null until POST /ingest has run successfully for this address.",
        example: "0xf06b2238bc2556a78fe1aee6cb173bbc5de5621a972a2473a5037724821ae625",
      },
      network: {
        type: "string",
        enum: ["mainnet"],
        nullable: true,
        description:
          "Always \"mainnet\" once set (this service has no testnet code path at all) -- null until ingestion has run.",
        example: "mainnet",
      },
      firstSeenMs: {
        type: "number",
        nullable: true,
        description:
          "Epoch milliseconds of the earliest transaction seen for this address, within the configured ingestion time window (see INGEST_WINDOW_START/END). Null until ingested.",
        example: 1768888919416,
      },
      lastSeenMs: {
        type: "number",
        nullable: true,
        description: "Epoch milliseconds of the most recent transaction seen for this address, within the ingestion window. Null until ingested.",
        example: 1785395591528,
      },
      txCount: {
        type: "number",
        description:
          "Number of transactions counted during the most recent ingestion run, within the ingestion time window. Not a lifetime total, and not derived from any stored transaction data (none is stored) -- purely a counter accumulated while paging through the Explorer API.",
        example: 30,
      },
      label: { ...walletLabel, nullable: true, description: walletLabel.description + "\n\n`null` if this wallet has never been classified." },
      botProbability: {
        type: "number",
        nullable: true,
        minimum: 0,
        maximum: 1,
        description:
          "The classifier's raw bot-probability score (0-1) that produced `label`. Exactly classifier-service/predict.py's `bot_probability` field, unmodified. Null if never classified.",
        example: 0.94,
      },
      classifiedAt: humanDateField("When `label`/`botProbability` were last written."),
      ingestionStatus: {
        type: "string",
        enum: ["pending", "in_progress", "complete", "failed"],
        description:
          "Lifecycle of the most recent (or in-flight) ingestion for this address:\n" +
          "- `pending` — record exists (usually created by a label write-back) but ingestion has never run.\n" +
          "- `in_progress` — POST /ingest is currently paging this address's transaction history.\n" +
          "- `complete` — the last ingestion run finished successfully; txCount/firstSeenMs/lastSeenMs reflect it.\n" +
          "- `failed` — the last ingestion run threw (e.g. malformed address, unreachable Explorer API); identity fields may be stale or absent.",
        example: "complete",
      },
      createdAt: humanDateField("When this wallet record was first created (by either POST /ingest or PATCH .../label, whichever happened first)."),
      updatedAt: humanDateField("When this wallet record was last modified in any way."),
    },
  };

  const errorBody = (exampleError: string) => ({
    type: "object",
    properties: { error: { type: "string", example: exampleError } },
  });

  return {
    openapi: "3.0.3",
    info: {
      title: "CKB Wallet Behaviour Intelligence -- registry-service API",
      description:
        "Wallet registry for the CKB Wallet Behaviour Intelligence project. This service does three things and nothing else: " +
        "(1) resolves a CKB address to its on-chain identity via POST /ingest, " +
        "(2) stores a classification label + confidence score for an address, written back by the separate classifier-service (Python) classifier, and " +
        "(3) re-publishes that classifier's evaluation metrics as JSON. " +
        "It does not run any model, does not fetch or store transaction data, and does not decide what label a wallet gets -- see the top-level README for the full two-service architecture.",
      version: "1.0.0",
    },
    servers: [{ url: `http://localhost:${config.apiPort}/api/v1`, description: "Local development" }],
    tags: [
      { name: "Health", description: "Liveness and chain connectivity checks." },
      { name: "Wallets", description: "Wallet identity lookups and classification label read/write." },
      { name: "Ingestion", description: "Resolves wallet identity from the CKB network -- the \"submit a wallet\" entry point." },
      { name: "Model", description: "Published evaluation metrics for the classifier that produces wallet labels." },
    ],
    paths: {
      "/health": {
        get: {
          tags: ["Health"],
          summary: "Liveness check",
          description:
            "Returns 200 with a static body as long as the HTTP server is up and able to handle requests. Does not check MongoDB or the CKB RPC/Explorer APIs -- use GET /chain/status for connectivity checks. Intended for load balancer / container orchestrator health probes.",
          responses: {
            "200": {
              description: "The server is up.",
              content: {
                "application/json": {
                  schema: { type: "object", properties: { status: { type: "string", example: "ok" } } },
                },
              },
            },
          },
        },
      },
      "/chain/status": {
        get: {
          tags: ["Health"],
          summary: "Current mainnet tip block (proves CKB RPC connectivity)",
          description:
            "Fetches the current tip block number from the public CKB mainnet RPC node via CCC, proving the service can actually reach the chain (not just that the HTTP server is up). " +
            "Cached for 5 seconds: the tip block doesn't need per-request freshness, and a live RPC round trip costs roughly 650ms-1000ms -- repeated calls within the cache window return in ~30-60ms instead of paying that cost every time. " +
            "Mainnet only; this service has no testnet code path.",
          responses: {
            "200": {
              description: "Chain is reachable.",
              content: {
                "application/json": {
                  schema: {
                    type: "object",
                    properties: {
                      network: { type: "string", enum: ["mainnet"], example: "mainnet" },
                      tipBlockNumber: { type: "number", description: "Current mainnet tip block height.", example: 20039769 },
                    },
                  },
                },
              },
            },
            "500": {
              description: "The CKB RPC node was unreachable when the cache last needed refreshing.",
              content: { "application/json": { schema: errorBody("connect ECONNREFUSED ...") } },
            },
          },
        },
      },
      "/wallets": {
        get: {
          tags: ["Wallets"],
          summary: "List wallets, optionally filtered by classification label",
          description:
            "Returns a paginated list of wallet records. Pass `label` to see only wallets currently classified as that value (e.g. every wallet the model has ever flagged as `bot`). Omit `label` to list every wallet regardless of classification state, including ones that have only been ingested (never labeled) or only labeled (never ingested).",
          parameters: [
            {
              name: "page",
              in: "query",
              description: "1-indexed page number.",
              schema: { type: "integer", default: 1, minimum: 1 },
            },
            {
              name: "pageSize",
              in: "query",
              description: "Results per page, capped at 200 regardless of what's requested.",
              schema: { type: "integer", default: 50, minimum: 1, maximum: 200 },
            },
            {
              name: "label",
              in: "query",
              description: "Filter to wallets with exactly this classification label. Omit to return wallets of every label (and unlabeled wallets).",
              required: false,
              schema: { type: "string", enum: ["bot", "human", "uncertain", "unknown"] },
            },
          ],
          responses: {
            "200": {
              description: "Paginated wallet list, sorted by most recently updated first.",
              content: {
                "application/json": {
                  schema: {
                    type: "object",
                    properties: {
                      items: { type: "array", items: wallet },
                      total: { type: "number", description: "Total matching wallets across all pages.", example: 12 },
                      page: { type: "number", example: 1 },
                      pageSize: { type: "number", example: 50 },
                    },
                  },
                },
              },
            },
            "400": {
              description: "`label` was provided but isn't one of bot/human/uncertain/unknown.",
              content: { "application/json": { schema: errorBody("invalid label -- must be one of bot, human, uncertain, unknown") } },
            },
          },
        },
      },
      "/wallets/{address}": {
        get: {
          tags: ["Wallets"],
          summary: "Fetch one wallet's identity + classification record",
          description: "Returns the full stored record for a single address: identity fields (if ever ingested) and classification fields (if ever labeled). Returns 404 if this service has never seen the address at all -- neither ingested nor labeled.",
          parameters: [
            {
              name: "address",
              in: "path",
              required: true,
              description: "A CKB mainnet address.",
              schema: { type: "string" },
              example: EXAMPLE_ADDRESS,
            },
          ],
          responses: {
            "200": { description: "Wallet found.", content: { "application/json": { schema: wallet } } },
            "404": {
              description: "No record exists for this address -- it has never been ingested or labeled.",
              content: {
                "application/json": {
                  schema: {
                    type: "object",
                    properties: { error: { type: "string", example: "wallet not found" }, address: { type: "string" } },
                  },
                },
              },
            },
          },
        },
      },
      "/wallets/{address}/label": {
        patch: {
          tags: ["Wallets"],
          summary: "Write back a classification result",
          description:
            "This is how a wallet gets classified: the classifier-service (Python) classifier calls this after scoring an address, sending back exactly the `verdict`/`bot_probability` it computed. " +
            "**Upserts** — if this address has never been seen by this service before (never ingested, never labeled), this call creates its record on the spot with just the address and the label fields populated; identity fields (lockScriptHash, network, etc.) stay null until/unless POST /ingest is separately called for it. This means a label can never be silently dropped just because ingestion hasn't happened yet, and there is deliberately no 404 response here.",
          parameters: [
            {
              name: "address",
              in: "path",
              required: true,
              description: "A CKB mainnet address. Doesn't need to already exist in this service.",
              schema: { type: "string" },
              example: EXAMPLE_ADDRESS,
            },
          ],
          requestBody: {
            required: true,
            description: "The classification result to store.",
            content: {
              "application/json": {
                schema: {
                  type: "object",
                  required: ["label"],
                  properties: {
                    label: walletLabel,
                    botProbability: {
                      type: "number",
                      minimum: 0,
                      maximum: 1,
                      description: "Optional. The model's raw probability score backing `label`. Stored as-is if provided; left null otherwise.",
                      example: 0.94,
                    },
                  },
                },
                example: { label: "bot", botProbability: 0.94 },
              },
            },
          },
          responses: {
            "200": {
              description: "Wallet record created or updated with the new label. Always 200, whether the record existed before or not.",
              content: { "application/json": { schema: wallet } },
            },
            "400": {
              description: "`label` was missing, or wasn't one of bot/human/uncertain/unknown.",
              content: {
                "application/json": {
                  schema: {
                    type: "object",
                    properties: {
                      error: { type: "string", example: "body.label is required and must be one of bot, human, uncertain, unknown" },
                      received: { type: "string", nullable: true, example: "exchange" },
                    },
                  },
                },
              },
            },
          },
        },
      },
      "/ingest": {
        post: {
          tags: ["Ingestion"],
          summary: "Resolve wallet identity for one or more addresses",
          description:
            "This is the \"submit a wallet\" endpoint. For each address: resolves it to its lock script / lock script hash via CCC, pages through its transaction history on the CKB Explorer API (bounded by the configured training time window), and upserts a Wallet record with the resulting identity + tx-count/first-seen/last-seen summary. " +
            "**No transaction data is stored** -- each transaction is folded into the running counters and discarded, never written to MongoDB. " +
            "Addresses are processed sequentially, and a failure on one address (malformed address, unreachable Explorer API) is caught and logged, not thrown -- it simply doesn't appear in `results`, and the request still returns 200. Existing classification labels on an address are never touched by ingestion.",
          requestBody: {
            required: true,
            content: {
              "application/json": {
                schema: {
                  type: "object",
                  required: ["addresses"],
                  properties: {
                    addresses: {
                      type: "array",
                      items: { type: "string" },
                      description: "One or more CKB mainnet addresses to resolve.",
                    },
                  },
                },
                example: { addresses: [EXAMPLE_ADDRESS] },
              },
            },
          },
          responses: {
            "200": {
              description: "Always 200 -- check `results.length` against `requested` to see if any addresses failed (failures are silently omitted, not errored).",
              content: {
                "application/json": {
                  schema: {
                    type: "object",
                    properties: {
                      requested: { type: "number", description: "How many addresses were in the request body.", example: 1 },
                      results: {
                        type: "array",
                        description: "One entry per address that ingested successfully. Shorter than `requested` if any address failed.",
                        items: {
                          type: "object",
                          properties: {
                            address: { type: "string", example: EXAMPLE_ADDRESS },
                            lockScriptHash: { type: "string", example: "0xf06b2238bc2556a78fe1aee6cb173bbc5de5621a972a2473a5037724821ae625" },
                            txIngested: { type: "number", description: "Transactions counted within the ingestion window.", example: 30 },
                            firstSeenMs: { type: "number", nullable: true, example: 1768888919416 },
                            lastSeenMs: { type: "number", nullable: true, example: 1785395591528 },
                          },
                        },
                      },
                    },
                  },
                },
              },
            },
            "400": {
              description: "`addresses` was missing, not an array, or empty.",
              content: {
                "application/json": {
                  schema: errorBody("body must be { addresses: string[] } with at least one address"),
                },
              },
            },
          },
        },
      },
      "/model/evaluation": {
        get: {
          tags: ["Model"],
          summary: "Latest classifier evaluation metrics",
          description:
            "Reads classifier-service/eval_results.json directly off disk on every request (not cached) and reshapes it into this response -- so it always reflects whatever the classifier's most recent training run (classifier-service/train_eval.py) produced, with no need to restart this service after a retrain. This service does not compute any of these numbers itself; it only re-serves what Python already wrote to disk.",
          responses: {
            "200": {
              description: "Evaluation metrics from the most recent training run.",
              content: {
                "application/json": {
                  schema: {
                    type: "object",
                    properties: {
                      modelSelected: {
                        type: "string",
                        description: "Which candidate model (of Logistic Regression / Random Forest / Gradient Boosting / RBF SVM) scored best on 5-fold cross-validation and was deployed.",
                        example: "RandomForest",
                      },
                      accuracy: { type: "number", description: "Held-out test set accuracy (0-1).", example: 0.9524 },
                      precision: { type: "number", description: "Held-out test set precision for the `bot` class (0-1).", example: 0.9512 },
                      recall: { type: "number", description: "Held-out test set recall for the `bot` class (0-1).", example: 0.975 },
                      f1Score: { type: "number", description: "Held-out test set F1 score for the `bot` class (0-1).", example: 0.963 },
                      rocAuc: { type: "number", description: "Held-out test set ROC-AUC (0-1).", example: 0.9924 },
                      confusionMatrix: {
                        type: "object",
                        description: "Held-out test set confusion matrix, counts of each outcome.",
                        properties: {
                          true_bot_pred_bot: { type: "number", example: 39 },
                          true_bot_pred_human: { type: "number", example: 1 },
                          true_human_pred_bot: { type: "number", example: 2 },
                          true_human_pred_human: { type: "number", example: 21 },
                        },
                      },
                      datasetStatistics: {
                        type: "object",
                        description: "Size of the labeled training dataset used for this training run.",
                        properties: {
                          nBotLike: { type: "number", example: 160 },
                          nHumanLike: { type: "number", example: 91 },
                          total: { type: "number", example: 251 },
                          nShortHistoryRows: { type: "number", description: "Rows with too little transaction history for interval-based features to be meaningful.", example: 57 },
                          minTxFilterApplied: { type: "number", description: "The --min-tx filter value used for this run, if any (0 = no filter).", example: 0 },
                        },
                      },
                      labelDistribution: {
                        type: "object",
                        description: "Class balance of the training dataset, as counts and percentages.",
                        properties: {
                          bot: {
                            type: "object",
                            properties: { count: { type: "number", example: 160 }, pct: { type: "number", example: 63.75 } },
                          },
                          human: {
                            type: "object",
                            properties: { count: { type: "number", example: 91 }, pct: { type: "number", example: 36.25 } },
                          },
                        },
                      },
                      cvModelComparison: {
                        type: "object",
                        description: "Per-candidate-model 5-fold cross-validation results (accuracy/precision/recall/f1/roc_auc mean+std), showing why `modelSelected` was chosen over the alternatives.",
                      },
                      featureImportance: {
                        type: "object",
                        description: "Feature importance scores from the selected (tree-based) model, highest first -- which behavioral signals actually drove the classification.",
                        example: { interval_max_over_mean: 0.2873, n_unique_counterparties: 0.1601 },
                      },
                      labelProvenanceWarning: {
                        type: "string",
                        description: "A caveat string, always present: the training labels are heuristic proxies, not verified ground truth, so these metrics are bounded by that heuristic's quality.",
                      },
                      lastUpdatedAt: {
                        type: "string",
                        description: "When eval_results.json was last written (i.e. when the classifier was last retrained), human-readable, e.g. \"Aug 2, 2026, 8:39 AM UTC\".",
                        example: EXAMPLE_DATE,
                      },
                    },
                  },
                },
              },
            },
            "503": {
              description: "eval_results.json doesn't exist yet -- the classifier has never been trained (run classifier-service/train_eval.py first).",
              content: {
                "application/json": {
                  schema: errorBody("eval_results.json not found at ... -- run classifier-service/train_eval.py first"),
                },
              },
            },
          },
        },
      },
    },
  };
}
