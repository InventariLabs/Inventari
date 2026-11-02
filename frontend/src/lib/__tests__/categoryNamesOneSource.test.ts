import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * A category's user-visible name has one source: `categories:codes.<code>`,
 * resolved through `categoryLabel` (lib/i18nHelpers.ts) — the record's
 * `name` is the seed's fallback, not a second display name.
 *
 * How two names for one category happened: the product form translated by
 * code ("Cold cuts") while the bulk-edit select printed the raw record name
 * ("Deli") — thirty rows apart in the same alphabet, and a reader who filed
 * ten products under "Cold cuts" could not find them in bulk edit.
 *
 * Two scans, because the regression has two shapes:
 * - building the translation key by hand instead of calling the resolver;
 * - rendering a raw category name.
 *
 * The raw scan used to have an opinion only about files that named a
 * category type, so a file rendering `item.category_name` without ever
 * writing `Category` was waved through whole. What can only be a category's
 * name — the wire field `category_name`, `category.name`, `{row.category}`
 * — is now a finding wherever it stands. Only the ambiguous shorthands
 * (`c.name`, `cat.name`) still need the file to be about categories.
 *
 * Known limit: a name reached indirectly — `categories.find(...)!.name`, a
 * destructured `{ name }` — is not a pattern a line scan can see.
 */

const SRC = join(process.cwd(), "src");

/** Where building the key by hand is the honest answer. */
const KEY_ALLOWED = [
  // The resolver itself — this is the key it owns.
  "lib/i18nHelpers.ts",
  // Quick-add's search matches what the reader types against the translated
  // name on purpose; it renders nothing.
  "modules/inventory/hooks/useQuickAdd.ts",
];

/** A hand-built `categories:codes.` key outside the resolver. */
const HAND_BUILT_KEY = /["'`]categories:codes\./;

/**
 * A category's name and nothing else, in any file: the wire field
 * `category_name`, `.name` read off something called `category`, and a
 * `category` string rendered into JSX or a template literal
 * (`{row.category}`, `${row.category}`) — the stats rows carry the name
 * under that key.
 */
const CATEGORY_NAME =
  /\.category_name\b|\bcategory\??\.name\b|\{\s*[\w$.?!]+\??\.category\s*\}/;

/**
 * `c.name` / `cat.name`: a category only in a file that deals in
 * categories. Elsewhere `c` is a connection, a location, anything.
 */
const SHORTHAND_NAME = /\bcat\b\??\.name\b|\bc\b\??\.name\b/;
const CATEGORY_FILE =
  /\bCategory\b|\bCategoryStats\b|\bArchivedCategoryBrief\b|category_id\b/;

/**
 * Raw names that are the honest answer. Each entry needs the file it
 * applies to and why the line survives; an entry that no longer matches
 * anything fails the suite, so the list cannot quietly outgrow the code.
 */
const RAW_ALLOWED: Array<{ file: string; matches: RegExp; why: string }> = [
  {
    // Searching matches the record's own name too: a code-less category has
    // no translation, and its name is what its owner typed.
    file: "modules/inventory/pages/CategoriesPage.tsx",
    matches: /cat\.name\.toLowerCase/,
    why: "code-less categories are searched by their own name",
  },
  {
    // Wire field of a rule: the live, translated name is resolved one line
    // above, and this is the fallback for a category since deleted.
    file: "modules/warehouse/pages/PutawayRulesPage.tsx",
    matches: /rule\.category_name/,
    why: "stored snapshot as the fallback for a deleted category",
  },
  {
    // The emoji guess and the colour hash read the record's own name: an
    // identity that changed with the reader's language would not be one.
    // The tooltip and accessible name go through the resolver.
    file: "components/ui/CategoryAvatar.tsx",
    matches: /name: category\.name,|hashName\(category\.name/,
    why: "emoji-guess input and colour hash, not a rendered name",
  },
  {
    // A React key is machine state, never rendered — the machine keeps the
    // raw value, the screen gets the label.
    file: "modules/stats/components/StatsDistributionGrid.tsx",
    matches: /category_name \|\| "category"/,
    why: "React list key, not a rendered name",
  },
  {
    // Vision's suggestion is matched against both the record's name and its
    // translation, so either spelling finds the category; nothing renders.
    file: "modules/inventory/hooks/useQuickAdd.ts",
    matches: /c\.name\.toLowerCase\(\) === catName/,
    why: "match, not a render — name and translation both resolve",
  },
  {
    // The vision model's own words, quoted back as what it suggested — a
    // free-text guess, not a category record with a code.
    file: "modules/inventory/hooks/useQuickAdd.ts",
    matches: /\$\{visionData\.category\}/,
    why: "the model's free-text guess, not a category record",
  },
];

/** Whole files the raw scan has no opinion about, with the reason. */
const RAW_FILE_EXEMPT: Array<{ file: RegExp; why: string }> = [
  {
    // Equipment owns a separate category universe with its own resolver
    // (getCategoryLabel, assetUtils.ts) — the resolution this gate guards
    // does not apply to it.
    file: /^modules\/equipment\//,
    why: "equipment's categories are a separate dataset with its own resolver",
  },
  {
    // `category_name` on a record's unit is the unit's category ("Unit",
    // "Weight") and is compared, never shown.
    file: /^utils\/partialPackage\.ts$/,
    why: "reads the unit category of a record to tell pieces from a pack, nothing rendered",
  },
];

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry === "__tests__") continue;
      out.push(...walk(full));
      continue;
    }
    if (!/\.tsx?$/.test(entry) || /\.test\.tsx?$/.test(entry)) continue;
    if (entry === "api-generated.ts" || entry === "api-routes.ts") continue;
    out.push(full);
  }
  return out;
}

/** `text` with everything but line breaks blanked, so line numbers hold. */
const blank = (text: string) => text.replace(/[^\n]/g, " ");

/**
 * The source with what is not a render blanked out: comments, and the
 * arguments of every `categoryLabel(...)` call — a resolver call names the
 * record in its arguments, and that is compliance, not a finding, however
 * many lines the call spans.
 */
function maskCompliant(source: string): string {
  let text = source
    .replace(/\/\*[\s\S]*?\*\//g, blank)
    .replace(
      /(^|[^:])(\/\/.*)$/gm,
      (_, lead: string, comment: string) => lead + blank(comment),
    );
  const call = /\bcategoryLabel\(/g;
  let match: RegExpExecArray | null;
  while ((match = call.exec(text)) !== null) {
    const open = match.index + match[0].length;
    let depth = 1;
    let end = open;
    while (end < text.length && depth > 0) {
      if (text[end] === "(") depth += 1;
      if (text[end] === ")") depth -= 1;
      end += 1;
    }
    text =
      text.slice(0, open) +
      blank(text.slice(open, end - 1)) +
      text.slice(end - 1);
  }
  return text;
}

/** Raw category names in one file, as `src/<file>:<line> — <line>`. */
function rawNameFindings(rel: string, source: string): string[] {
  const aboutCategories = CATEGORY_FILE.test(source);
  const original = source.split("\n");
  const findings: string[] = [];
  maskCompliant(source)
    .split("\n")
    .forEach((line, index) => {
      const hit =
        CATEGORY_NAME.test(line) ||
        (aboutCategories && SHORTHAND_NAME.test(line));
      if (!hit) return;
      const raw = original[index];
      if (RAW_ALLOWED.some((a) => a.file === rel && a.matches.test(raw))) {
        return;
      }
      findings.push(`src/${rel}:${index + 1} — ${raw.trim()}`);
    });
  return findings;
}

function scanFiles(): Array<{ rel: string; source: string }> {
  return walk(SRC).map((file) => ({
    rel: relative(SRC, file),
    source: readFileSync(file, "utf8"),
  }));
}

describe("a category is named in one place", () => {
  it("finds files to scan (the gate is not vacuous)", () => {
    expect(walk(SRC).length).toBeGreaterThan(100);
  });

  it("has no screen building a categories:codes key by hand", () => {
    const findings = scanFiles()
      .filter(({ rel }) => !KEY_ALLOWED.includes(rel))
      .flatMap(({ rel, source }) =>
        source
          .split("\n")
          .flatMap((line, index) =>
            HAND_BUILT_KEY.test(line) && !/categoryLabel\(/.test(line)
              ? [`src/${rel}:${index + 1} — ${line.trim()}`]
              : [],
          ),
      );
    expect(findings).toEqual([]);
  });

  it("has no screen rendering a raw category name", () => {
    const findings = scanFiles()
      .filter(({ rel }) => !RAW_FILE_EXEMPT.some((e) => e.file.test(rel)))
      .flatMap(({ rel, source }) => rawNameFindings(rel, source));
    expect(findings).toEqual([]);
  });

  it("fires on the bulk-edit regression it exists for", () => {
    // The bulk-edit select used to render exactly this line.
    const findings = rawNameFindings(
      "modules/inventory/components/items/BulkEditModal.tsx",
      [
        "import type { Category } from '@/types';",
        "{categories?.map((c) => (",
        "  <option key={c.id}>{c.name}</option>",
        "))}",
      ].join("\n"),
    );
    expect(findings).toEqual([
      "src/modules/inventory/components/items/BulkEditModal.tsx:3 — <option key={c.id}>{c.name}</option>",
    ]);
  });

  it("fires on a wire category_name in a file that never names a category", () => {
    // The command palette printed `item.category_name` through two rounds
    // of review while the file filter kept the whole file out of the scan.
    const findings = rawNameFindings(
      "lib/useCommandPaletteSearch.ts",
      "    subtitle: item.barcode ??\n      item.category_name ??\n      undefined,",
    );
    expect(findings).toEqual([
      "src/lib/useCommandPaletteSearch.ts:2 — item.category_name ??",
    ]);
  });

  it("fires on a stats row's category rendered as it came", () => {
    // The rotation card's slow movers printed `{item.category}` — the name,
    // under the key the stats rows carry it.
    const findings = rawNameFindings(
      "modules/stats/components/RotationAnalysisCard.tsx",
      '<p className="text-xs">{item.category}</p>',
    );
    expect(findings).toHaveLength(1);
  });

  it("reads a categoryLabel call across lines as compliance", () => {
    // Prettier breaks a long resolver call over lines; its arguments name
    // the record and must not read as a raw render. Nor does a comment.
    expect(
      rawNameFindings(
        "modules/stats/components/StatsCostAnalysis.tsx",
        [
          "{categoryLabel(",
          "  t,",
          "  opp.category_code,",
          "  opp.category_name,",
          ")}",
          "// the old code printed {opp.category_name} here",
        ].join("\n"),
      ),
    ).toEqual([]);
  });

  it("a foreign file's c.name is nobody's category", () => {
    // Outside category files the shorthand has no opinion, or every `c.name`
    // in the app would be a finding.
    expect(
      rawNameFindings(
        "modules/settings/components/ai/AiConnectionFormModal.tsx",
        "c.name.trim().toLowerCase() === name.toLowerCase()",
      ),
    ).toEqual([]);
  });

  it("every allowlist entry still matches the line it excuses", () => {
    // An entry outliving its line would wave the next one through.
    const stale = RAW_ALLOWED.filter(
      (a) =>
        !readFileSync(join(SRC, a.file), "utf8")
          .split("\n")
          .some((line) => a.matches.test(line)),
    ).map((a) => `${a.file} — ${a.why}`);
    expect(stale).toEqual([]);
  });

  it("the resolver itself still owns the key", () => {
    // The gate is not allowed to silence the one file that should carry it.
    const rel = "lib/i18nHelpers.ts";
    expect(HAND_BUILT_KEY.test(readFileSync(join(SRC, rel), "utf8"))).toBe(
      true,
    );
  });

  it("a code mirrored in a module's namespace says what the shared catalogue says", () => {
    // The shared `categories` catalogue carries every module's seeded codes,
    // and a module may mirror its own codes in its own namespace for screens
    // inside the module. The mirror exists so those screens resolve without
    // reaching across the shell — it is not a second opinion about the name.
    // One code, one name, in every language the app speaks.
    const langs = readdirSync(join(process.cwd(), "src/i18n/locales"));
    for (const lang of langs) {
      const shared = JSON.parse(
        readFileSync(
          join(process.cwd(), `src/i18n/locales/${lang}/categories.json`),
          "utf8",
        ),
      ).codes as Record<string, string>;
      const moduleFile = join(
        process.cwd(),
        `src/modules/equipment/i18n/${lang}.json`,
      );
      const mirrored = (JSON.parse(readFileSync(moduleFile, "utf8")).categories
        ?.codes ?? {}) as Record<string, string>;
      for (const [code, name] of Object.entries(mirrored)) {
        expect(
          shared[code],
          `the shared catalogue has no name for ${code} (${lang})`,
        ).toBeDefined();
        expect(
          shared[code],
          `${code} reads "${shared[code]}" in the shared catalogue where the ` +
            `equipment namespace reads "${name}" (${lang})`,
        ).toBe(name);
      }
    }
  });
});
