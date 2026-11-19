import type { E2EConfig } from "e2e";
import { web } from "@e2e-dev/web";

export default {
  tests: "tests/**/*.e2e.ts",
  targets: [{ name: "chromium", engine: web({ reducedMotion: "reduce" }), app: { url: "http://127.0.0.1:5174" } }],
  timeout: 120_000,
  assertionTimeout: 20_000,
  workers: 1,
  retries: 0,
  reporters: ["list"],
} satisfies E2EConfig;
