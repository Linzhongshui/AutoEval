#!/usr/bin/env node
// Dependency boundaries for the frontend layout:
//   shared/  -> must not import features/ or app/
//   features/* -> must not import app/
//   hand-written types must not redeclare generated OpenAPI schema names
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve, dirname } from "node:path";

const root = resolve(process.cwd(), "src");
const problems = [];

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    return statSync(full).isDirectory() ? walk(full) : [full];
  });
}

const files = walk(root).filter((file) => file.endsWith(".ts") || file.endsWith(".tsx"));
const imports = /from\s+["'](\.[^"']+)["']/g;

for (const file of files) {
  const rel = relative(root, file).replaceAll("\\", "/");
  const text = readFileSync(file, "utf8");
  for (const match of text.matchAll(imports)) {
    const target = relative(root, resolve(dirname(file), match[1])).replaceAll("\\", "/");
    if (rel.startsWith("shared/") && (target.startsWith("features/") || target.startsWith("app/"))) {
      problems.push(`${rel} imports ${target}; shared must not depend on business modules`);
    }
    if (rel.startsWith("features/") && target.startsWith("app/")) {
      problems.push(`${rel} imports ${target}; features must not depend on app`);
    }
  }
}

const generated = readFileSync(join(root, "shared/types/api.ts"), "utf8");
const schemaBlock = generated.slice(generated.indexOf("schemas: {"));
const generatedNames = new Set(
  [...schemaBlock.matchAll(/^\s{8}(\w+): \{/gm)].map((match) => match[1]),
);

for (const file of files) {
  const rel = relative(root, file).replaceAll("\\", "/");
  if (rel === "shared/types/api.ts") continue;
  const text = readFileSync(file, "utf8");
  for (const match of text.matchAll(/(?:export\s+)?type\s+(\w+)\s*=\s*([^;\n]*)/g)) {
    if (!generatedNames.has(match[1])) continue;
    // Aliasing the generated type is the intended usage; redefining it is not.
    if (match[2].includes('components["schemas"]')) continue;
    problems.push(
      `${rel} redeclares generated schema type ${match[1]}; import components["schemas"] instead`,
    );
  }
}

if (problems.length) {
  console.error(problems.join("\n"));
  process.exit(1);
}
console.log(`frontend boundaries ok (${files.length} files)`);
