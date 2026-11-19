import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const ts = require("typescript");

export function loadTypeScript(relativePath, imports = {}, globals = {}) {
  const path = fileURLToPath(new URL(relativePath, import.meta.url));
  const source = readFileSync(path, "utf8").replaceAll("import.meta.env", "({ VITE_API_BASE_URL: '' })");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS, esModuleInterop: true },
    fileName: path
  });
  const module = { exports: {} };
  const loadImport = (name) => imports[name] ?? require(name);
  const execute = new Function("require", "module", "exports", ...Object.keys(globals), compiled.outputText);
  execute(loadImport, module, module.exports, ...Object.values(globals));
  return module.exports;
}
