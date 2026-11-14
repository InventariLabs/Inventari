import { describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readdirSync, readFileSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import * as prettier from "prettier";
import {
  coreImports,
  crossings,
  MODULE_API_FILE,
} from "./check-module-boundaries.mjs";

const SCRIPT = join(import.meta.dirname, "generate_module.js");

/** Every file the generator writes, as [relative path, text]. */
function generate(name) {
  const root = mkdtempSync(join(tmpdir(), "scaffold-"));
  execFileSync("node", [SCRIPT, name], {
    env: { ...process.env, MODULE_SCAFFOLD_ROOT: root },
    stdio: "pipe",
  });
  const files = [];
  const walk = (dir, rel) => {
    for (const entry of readdirSync(dir)) {
      const path = join(dir, entry);
      if (statSync(path).isDirectory()) walk(path, `${rel}${entry}/`);
      else files.push([`${rel}${entry}`, readFileSync(path, "utf8")]);
    }
  };
  walk(join(root, name), "");
  return files;
}

describe("generate_module", () => {
  // The module-boundaries gate in the pre-commit hook refuses a module file
  // that imports Core past @/module-sdk, so a scaffold that did would fail its
  // author's first commit: module.ts imported @/lib/moduleRegistry and the
  // page @/hooks/useModulePageHeader.
  it("imports Core only through the module SDK", () => {
    const crossings = generate("warranty_tracker")
      .filter(([path]) => /\.tsx?$/.test(path))
      .flatMap(([path, text]) => coreImports(`warranty_tracker/${path}`, text));
    expect(crossings).toEqual([]);
  });

  // knip fails check-frontend on a file nothing imports: the scaffold wrote a
  // types/index.ts holding only a comment. Every TypeScript file it writes is
  // reached from a file knip.json names as an entry: module.ts, which the
  // shell discovers, or moduleApi.ts, which other modules import.
  it("writes no TypeScript file that knip cannot reach", () => {
    const knip = readFileSync(
      join(import.meta.dirname, "..", "knip.json"),
      "utf8",
    );
    const entries = ["module.ts", `${MODULE_API_FILE}.ts`];
    for (const entry of entries) {
      expect(knip).toContain(`"src/modules/*/${entry}"`);
    }

    const files = Object.fromEntries(generate("warranty_tracker"));
    const reached = new Set(entries);
    const queue = [...entries];
    while (queue.length > 0) {
      const from = queue.pop();
      for (const match of files[from].matchAll(
        /from "\.\/([^"]+)"|import\("\.\/([^"]+)"\)/g,
      )) {
        const spec = match[1] ?? match[2];
        const target = Object.keys(files).find(
          (path) => path === `${spec}.ts` || path === `${spec}.tsx`,
        );
        if (target && !reached.has(target)) {
          reached.add(target);
          queue.push(target);
        }
      }
    }
    const typescript = Object.keys(files).filter((path) => /\.tsx?$/.test(path));
    expect(typescript.filter((path) => !reached.has(path))).toEqual([]);
  });

  // check:boundaries lets another module in through one file and counts any
  // other path into the module as an edge. A module created without that file
  // leaves its first dependant to work out where the door goes, and the
  // nearest guess is the deep import the gate refuses.
  it("writes the one file other modules may import it through", () => {
    const files = Object.fromEntries(generate("warranty_tracker"));
    const door = files[`${MODULE_API_FILE}.ts`];
    expect(door).toBeDefined();

    // Empty: a name goes in when a second module needs it.
    expect(door).not.toMatch(/^export\b/m);

    const modules = new Set(["purchase_orders", "warranty_tracker"]);
    const into = (path) =>
      crossings(
        "purchase_orders/pages/X.tsx",
        `import { a } from "@/modules/warranty_tracker/${path}";`,
        modules,
      );
    expect(into(MODULE_API_FILE)).toEqual([]);
    expect(into("pages/IndexPage")).toEqual([
      "purchase_orders/pages/X.tsx → warranty_tracker",
    ]);
  });

  // A scaffold the formatter rejects fails its author's first commit: the
  // pre-commit hook runs prettier --check over src/, and module.ts came out
  // in single quotes.
  it("writes files prettier already accepts", async () => {
    const files = generate("warranty_tracker");
    expect(files.map(([path]) => path)).toContain("module.ts");

    const rejected = [];
    for (const [path, text] of files) {
      if (!/\.(ts|tsx|json)$/.test(path)) continue;
      const filepath = join(
        import.meta.dirname,
        "..",
        "src",
        "modules",
        "warranty_tracker",
        path,
      );
      const options = await prettier.resolveConfig(filepath);
      if (!(await prettier.check(text, { ...options, filepath }))) {
        rejected.push(path);
      }
    }
    expect(rejected).toEqual([]);
  });

  // `make new-module` runs both scaffolds: the backend copies the reference
  // module's manifest, whose permissions name their labels in the module's
  // namespace, and check:i18n fails the new module until every language holds
  // them. Read from the manifest the backend copies, not restated here.
  it("holds the permission labels the backend scaffold declares", () => {
    const manifest = JSON.parse(
      readFileSync(
        join(
          import.meta.dirname,
          "..",
          "..",
          "backend",
          "app",
          "modules",
          "example_widgets",
          "manifest.json",
        ),
        "utf8",
      ),
    );
    const keys = manifest.permissions.flatMap((p) =>
      [p.label_key, p.description_key].map((k) =>
        k.replace(/^example_widgets:/, ""),
      ),
    );
    expect(keys.length).toBeGreaterThan(0);

    const files = Object.fromEntries(generate("warranty_tracker"));
    for (const lang of ["en", "pl", "de", "fr", "es"]) {
      const catalog = JSON.parse(files[`i18n/${lang}.json`]);
      for (const key of keys) {
        const value = key.split(".").reduce((node, part) => node?.[part], catalog);
        expect(typeof value, `${lang}: ${key}`).toBe("string");
      }
    }
  });

  // The launcher lists only modules that declare a tile: without one, a module
  // made by `make new-module` is switched on and reachable only by its address.
  it("gives the module a home-screen tile whose text the catalogs hold", () => {
    const files = Object.fromEntries(generate("warranty_tracker"));
    const launcher = files["module.ts"].match(/launcher: \{([^}]*)\}/);
    expect(launcher).not.toBeNull();

    const keys = [...launcher[1].matchAll(/"warranty_tracker:([\w.]+)"/g)].map(
      (m) => m[1],
    );
    expect(keys).toHaveLength(2);
    for (const lang of ["en", "pl", "de", "fr", "es"]) {
      const catalog = JSON.parse(files[`i18n/${lang}.json`]);
      for (const key of keys) {
        const value = key.split(".").reduce((node, part) => node?.[part], catalog);
        expect(typeof value, `${lang}: ${key}`).toBe("string");
      }
    }
  });
});
