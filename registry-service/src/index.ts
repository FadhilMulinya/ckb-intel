import { startServer } from "./server.js";

startServer().catch((err) => {
  console.error("[fatal]", err);
  process.exit(1);
});
