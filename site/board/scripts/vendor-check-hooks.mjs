/**
 * Module hooks for scripts/check-vendor-agreement.mjs. The
 * board's TypeScript resolves through the bundler's rules
 * (the "@" alias for the board root, extensionless relative
 * imports, JSON modules without import attributes); these
 * hooks give plain Node the same resolution so the check can
 * execute the board's real resolver modules instead of
 * reimplementing them.
 */
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const BOARD = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const BOARD_URL = pathToFileURL(path.join(BOARD, "x")).href.slice(0, -1);

export async function resolve(specifier, context, next) {
  let rel = null;
  if (specifier.startsWith("@/")) {
    rel = specifier.slice(2);
  } else if (
    (specifier.startsWith("./") || specifier.startsWith("../")) &&
    context.parentURL &&
    context.parentURL.startsWith(BOARD_URL)
  ) {
    const parent = fileURLToPath(context.parentURL);
    rel = path.relative(BOARD, path.join(path.dirname(parent), specifier));
  }
  if (rel !== null && !rel.startsWith("..")) {
    const abs = path.join(BOARD, rel);
    for (const cand of [
      abs,
      `${abs}.ts`,
      `${abs}.tsx`,
      `${abs}.json`,
      path.join(abs, "index.ts"),
    ]) {
      if (existsSync(cand)) {
        return { url: pathToFileURL(cand).href, shortCircuit: true };
      }
    }
  }
  return next(specifier, context);
}

export async function load(url, context, next) {
  if (url.endsWith(".json")) {
    const text = readFileSync(fileURLToPath(url), "utf8");
    return {
      format: "module",
      source: `export default ${text};`,
      shortCircuit: true,
    };
  }
  return next(url, context);
}
