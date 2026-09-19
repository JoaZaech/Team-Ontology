import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const dependencyRoot = process.env.CODEX_NODE_MODULES ??
  "/Users/nurat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules";
const require = createRequire(path.join(dependencyRoot, "package.json"));
const { instance } = require("@viz-js/viz");
const sharp = require("sharp");

const here = path.dirname(fileURLToPath(import.meta.url));
const viz = await instance();
const dotFiles = (await fs.readdir(here)).filter((name) => name.endsWith(".dot")).sort();

for (const dotName of dotFiles) {
  const stem = dotName.slice(0, -4);
  const dot = await fs.readFile(path.join(here, dotName), "utf8");
  const svg = viz.renderString(dot, { format: "svg", engine: "dot" });
  await fs.writeFile(path.join(here, `${stem}.svg`), svg);
  await sharp(Buffer.from(svg)).resize({ width: 2400 }).png().toFile(path.join(here, `${stem}.png`));
}
