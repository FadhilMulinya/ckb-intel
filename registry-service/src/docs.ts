import { FastifyInstance } from "fastify";
import { buildOpenApiDocument } from "./openapi.js";

/**
 * Registers /openapi.json (the spec) and /docs (Scalar's API Reference UI,
 * loaded from CDN client-side, pointed at /openapi.json). Called from
 * routes/v1/index.ts inside the /api/v1 prefix group, so these resolve as
 * /api/v1/docs and /api/v1/openapi.json -- versioned alongside the rest of
 * the API, not a separate unversioned surface. No new runtime dependency:
 * Scalar ships as a single script tag, nothing to bundle.
 */
export function registerDocs(app: FastifyInstance): void {
  app.get("/openapi.json", async (_request, reply) => {
    reply.send(buildOpenApiDocument());
  });

  app.get("/docs", async (_request, reply) => {
    reply.type("text/html").send(`<!doctype html>
<html>
  <head>
    <title>CKB Wallet Behaviour Intelligence -- registry-service API docs</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
  </head>
  <body>
    <script id="api-reference" data-url="/api/v1/openapi.json"></script>
    <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
  </body>
</html>`);
  });
}
