/**
 * The i18n key gate, exercised end to end.
 *
 * Every case writes a fixture and runs the gate as a subprocess: the scanner
 * reads a tree, not a file it is handed, so this is the only way to ask it
 * what it would say about a given file.
 *
 * The fixtures live in a temporary directory the gate scans beside `src/`
 * (`I18N_EXTRA_SRC`), never in `src/` itself. They used to be written there,
 * under names meant to keep other globs away — but the other scanners in the
 * same vitest pass walk all of `src/`, and one of them listed a fixture a
 * moment before this file deleted it, then failed reading it with ENOENT: a
 * red suite with no failed assertion, in a branch that touched no frontend
 * code. A killed run also left the fixtures behind for tsc, eslint and
 * `git add` to find.
 */
import { execFileSync, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  existsSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  mkdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { afterAll, afterEach, describe, expect, it } from "vitest";

// Vitest serves this file through its own transform, so `import.meta.url`
// points at a virtual path. The runner's cwd is the frontend package.
const ROOT = process.cwd();
const SANDBOX = mkdtempSync(join(tmpdir(), "i18n-gate-"));
const GATE_ENV = { I18N_EXTRA_SRC: SANDBOX };
const FIXTURES = [
  resolve(SANDBOX, "__i18n_namespace_fixture__/UnqualifiedFixture.tsx"),
  resolve(SANDBOX, "__i18n_nested_fixture__/NestedFixture.tsx"),
  resolve(SANDBOX, "__i18n_placeholder_fixture__/PlaceholderFixture.tsx"),
  resolve(SANDBOX, "__i18n_table_fixture__/TableFixture.tsx"),
  resolve(SANDBOX, "__i18n_ternary_fixture__/TernaryFixture.tsx"),
];
const [UNQUALIFIED, NESTED, PLACEHOLDER, TABLE, TERNARY] = FIXTURES;

function runGate() {
  try {
    return {
      code: 0,
      out: execFileSync("node", ["scripts/check-i18n-keys.mjs", "--baseline"], {
        cwd: ROOT,
        encoding: "utf8",
        env: { ...process.env, ...GATE_ENV },
        stdio: ["ignore", "pipe", "pipe"],
      }),
    };
  } catch (error) {
    return {
      code: error.status ?? 1,
      out: `${error.stdout ?? ""}${error.stderr ?? ""}`,
    };
  }
}

function writeFixture(path, lines) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${lines.join("\n")}\n`);
}

afterEach(() => {
  for (const path of FIXTURES)
    rmSync(dirname(path), { recursive: true, force: true });
});

afterAll(() => {
  rmSync(SANDBOX, { recursive: true, force: true });
});

const fixturesInSrc = () =>
  [resolve(ROOT, "src"), resolve(ROOT, "src/modules")].flatMap((dir) =>
    existsSync(dir)
      ? readdirSync(dir).filter((name) => name.startsWith("__i18n_"))
      : [],
  );

describe("the gate's fixtures", () => {
  it("stay out of src/ while the gate reads them", () => {
    writeFixture(NESTED, [
      'import { useTranslation } from "react-i18next";',
      "export default function NestedFixture() {",
      "  const { t } = useTranslation();",
      '  return <span>{t("nested.fixture.sandboxProbe")}</span>;',
      "}",
    ]);

    const { out } = runGate();

    // The gate saw the file, so it was scanned from where it actually is...
    expect(out).toContain("MISSING common:nested.fixture.sandboxProbe");
    // ...and nothing a sibling scanner walks could have listed it.
    expect(fixturesInSrc()).toEqual([]);
  });
});

/**
 * `t(cond ? "a" : "b")` with a condition that quotes its own value.
 *
 * The ternary shape has been gated since the torch button announced itself as
 * "torchOn", but its condition class excluded quotes — so
 * `t(groupBy === "location" ? "a" : "b")` never matched at all and the
 * register signed its partner-less group with the raw key while the gate
 * reported zero missing keys. The same shape escaping twice is the point of
 * the case: the class may not exclude the very thing a condition is made of.
 */
describe('t(x === "a" ? "k1" : "k2")', () => {
  const ternary = (call) => [
    'import { useTranslation } from "react-i18next";',
    "export default function TernaryFixture() {",
    '  const { t } = useTranslation("warehouse");',
    `  return <span>{${call}}</span>;`,
    "}",
  ];

  it("reports both keys when the condition quotes its value", () => {
    writeFixture(
      TERNARY,
      ternary(
        't(groupBy === "location" ? "register.sandboxNoLocation" : "register.sandboxNoPartner")',
      ),
    );

    const { code, out } = runGate();

    expect(out).toContain("register.sandboxNoLocation");
    expect(out).toContain("register.sandboxNoPartner");
    expect(code).toBe(1);
  });

  it("says nothing once both keys exist", () => {
    writeFixture(
      TERNARY,
      ternary(
        't(groupBy === "location" ? "register.noLocationGroup" : "register.noPartnerGroup")',
      ),
    );

    const { code, out } = runGate();

    expect(out).not.toContain("register.noLocationGroup");
    expect(out).not.toContain("register.noPartnerGroup");
    expect(code).toBe(0);
  });
});

/**
 * A file that receives `t` as a prop states nothing about its namespaces: the
 * caller decides, and the scanner's fallback to `common` is a guess that
 * happens to be right often enough to hide the times it is not. In
 * `PurchasePatternsGrid` the parent passed `tFor("stats")`, four labels asked
 * for `analytics.patterns.*` with no prefix, i18next looked in `stats`, found
 * nothing, and rendered the English `defaultValue` beside Polish headings —
 * while the gate reported zero missing keys, because `common` does hold those
 * keys.
 */
describe("t() in a file that does not own its translator", () => {
  const borrowed = (call) => [
    "export default function UnqualifiedFixture({",
    "  t,",
    "}: {",
    "  t: (key: string, opts?: Record<string, unknown>) => string;",
    "}) {",
    `  return <span>{${call}}</span>;`,
    "}",
  ];

  it("is reported when the key names no namespace", () => {
    writeFixture(UNQUALIFIED, borrowed('t("analytics.patterns.avgPrice")'));

    const { code, out } = runGate();

    expect(out).toContain("UNQUALIFIED analytics.patterns.avgPrice");
    expect(code).toBe(1);
  });

  it("passes once the key says where it lives", () => {
    writeFixture(
      UNQUALIFIED,
      borrowed('t("common:analytics.patterns.avgPrice")'),
    );

    const { code, out } = runGate();

    expect(out).not.toContain("UNQUALIFIED");
    expect(code).toBe(0);
  });
});

/**
 * The scanner used to read a call's arguments as "anything up to the first
 * `)`". In `t("a", { unit: x ?? t("b") })` that parenthesis belongs to the
 * inner call, so the scan resumed past it and `b` was never looked at — a key
 * missing from all five catalogs rendered as its own name on screen while the
 * gate reported nothing.
 */
describe("a key passed to an enclosing t() call", () => {
  const owned = (body) => [
    'import { useTranslation } from "react-i18next";',
    "",
    "export default function NestedFixture() {",
    '  const { t } = useTranslation("common");',
    `  return ${body};`,
    "}",
  ];

  it("is checked when the whole call sits on one line", () => {
    writeFixture(
      NESTED,
      owned(
        '<span>{t("actions.save", { unit: t("nested.fixture.oneLine") })}</span>',
      ),
    );

    const { code, out } = runGate();

    expect(out).toContain("MISSING common:nested.fixture.oneLine");
    // The finding names the languages that lack the key, and the refusal
    // below tells the reader what to do — both in the language of the tree.
    expect(out).toMatch(/MISSING common:nested\.fixture\.oneLine.*missing in /);
    expect(out).toContain(
      "new violations — add the keys to the catalogues (×5 languages) or fix the t() call.",
    );
    expect(out).toMatch(/check-i18n-keys: \d+ t\(\) calls \| \d+ missing keys/);
    expect(code).toBe(1);
  });

  it("is checked when the call is broken across lines", () => {
    writeFixture(
      NESTED,
      owned(
        [
          "(",
          "    <span>",
          '      {t("actions.save", {',
          '        unit: t("nested.fixture.multiLine"),',
          "      })}",
          "    </span>",
          "  )",
        ].join("\n"),
      ),
    );

    const { code, out } = runGate();

    expect(out).toContain("MISSING common:nested.fixture.multiLine");
    expect(code).toBe(1);
  });

  it("does not cost the enclosing call its own check", () => {
    // Resuming the scan inside the call must not make the outer key invisible.
    writeFixture(
      NESTED,
      owned(
        '<span>{t("nested.fixture.outer", { unit: t("actions.save") })}</span>',
      ),
    );

    const { out } = runGate();

    expect(out).toContain("MISSING common:nested.fixture.outer");
  });

  it("says nothing when both keys exist", () => {
    writeFixture(
      NESTED,
      owned('<span>{t("actions.save", { unit: t("actions.cancel") })}</span>'),
    );

    const { code, out } = runGate();

    expect(out).not.toContain("MISSING");
    expect(code).toBe(0);
  });
});

/**
 * A translation that names a placeholder is a promise the call has to keep.
 * i18next reads a string second argument as a default value, so
 * `t("templates.refreshedCopy", `Created "${tpl.name}"`)` passes no variables
 * at all: the default never runs (the key exists), and `{{name}}` reaches the
 * screen as itself. Three delete dialogs asked the user to confirm removing a
 * record called `{{name}}`.
 */
describe("a placeholder with nothing to fill it", () => {
  const page = (call) => [
    'import { useTranslation } from "react-i18next";',
    "",
    "export default function PlaceholderFixture({ name }: { name: string }) {",
    '  const { t } = useTranslation("common");',
    `  return <span>{${call}}</span>;`,
    "}",
  ];

  it("is reported when the second argument is a template literal", () => {
    writeFixture(
      PLACEHOLDER,
      page('t("templates.refreshedCopy", `Created "${name}"`)'),
    );

    const { code, out } = runGate();

    expect(out).toContain("PLACEHOLDER common:templates.refreshedCopy");
    expect(out).toContain(
      "the second argument to t() is a default value, not an interpolation",
    );
    expect(code).toBe(1);
  });

  it("passes once the name is handed over as interpolation", () => {
    writeFixture(PLACEHOLDER, page('t("templates.refreshedCopy", { name })'));

    const { code, out } = runGate();

    expect(out).not.toContain("PLACEHOLDER");
    expect(code).toBe(0);
  });

  it("leaves the three-argument form alone", () => {
    // t(key, defaultValue, options) is i18next's own signature, and nine of
    // the twelve calls this rule first reported were this shape, interpolating
    // correctly. A default value beside an options object is not the defect.
    writeFixture(
      PLACEHOLDER,
      page('t("templates.refreshedCopy", "Created {{name}}", { name })'),
    );

    const { code, out } = runGate();

    expect(out).not.toContain("PLACEHOLDER");
    expect(code).toBe(0);
  });

  it("says nothing about a default value for a key with no placeholder", () => {
    writeFixture(PLACEHOLDER, page('t("actions.save", "Save")'));

    const { code, out } = runGate();

    expect(out).not.toContain("PLACEHOLDER");
    expect(code).toBe(0);
  });
});

/**
 * A key reached through a constant table is still a key.
 *
 * `t(PERIOD_KEYS[forecast.period], { ns: "common" })` reads as dynamic, so the
 * scanner said nothing about it and reported "0 missing keys" while three of
 * the six expiry-forecast tiles rendered DASHBOARD.TODAY. The table sits four
 * lines above the call, in the same file, and can simply be read.
 */
describe("keys supplied by a constant table", () => {
  const grid = (entries) => [
    'import { useTranslation } from "react-i18next";',
    "",
    "const PERIOD_KEYS: Record<string, string> = {",
    ...entries.map(([period, key]) => `  "${period}": "${key}",`),
    "};",
    "",
    "export default function TableFixture({ period }: { period: string }) {",
    '  const { t } = useTranslation("common");',
    '  return <span>{t(PERIOD_KEYS[period], { ns: "common" })}</span>;',
    "}",
  ];

  it("reports the one entry no catalog can serve", () => {
    writeFixture(
      TABLE,
      grid([
        ["Expired", "dashboard.expired"],
        ["Today", "dashboard.notAKeyAnyoneWrote"],
      ]),
    );

    const { code, out } = runGate();

    expect(out).toContain("MISSING common:dashboard.notAKeyAnyoneWrote");
    expect(code).toBe(1);
  });

  it("passes when every entry names a key that exists", () => {
    writeFixture(
      TABLE,
      grid([
        ["Expired", "dashboard.expired"],
        ["Today", "dashboard.today"],
        ["Tomorrow", "dashboard.tomorrow"],
        ["This week", "dashboard.thisWeek"],
        ["Next 2 weeks", "dashboard.next2Weeks"],
        ["This month", "dashboard.thisMonth"],
      ]),
    );

    const { code, out } = runGate();

    expect(out).not.toContain("MISSING");
    expect(code).toBe(0);
  });
});

/**
 * Presence is not content. A family rewrite that touched `_one` and `_other`
 * — the forms English thinks in — while Polish actually speaks `_few`/`_many`
 * for 2 and up once let a location-delete dialog call the same records by two
 * different nouns in one breath: every form existed, the gate stayed green,
 * and the row on the screen contradicted the dialog beside it.
 *
 * The gate cannot judge content from the tree alone, so the reference is a
 * snapshot of every family's form hashes; these tests drive it through the
 * env overrides so the tree's own files are never touched.
 */
describe("a plural family whose sentence changed in some forms only", () => {
  const MODULE_DIR = resolve(SANDBOX, "modules/__i18n_plural_fixture__");
  const CATALOG = resolve(MODULE_DIR, "i18n/pl.json");
  const FAMILY = "__i18n_plural_fixture__|pl|widget.counts";
  const OLD = {
    one: "1 rekord",
    few: "{{count}} rekordy",
    many: "{{count}} rekordów",
    other: "{{count}} rekordu",
  };
  const NEW = {
    one: "1 zasób",
    few: OLD.few,
    many: OLD.many,
    other: "{{count}} zasobów",
  };

  const hash = (value) =>
    createHash("sha256").update(value).digest("hex").slice(0, 12);

  const snapshotOf = (forms) =>
    JSON.stringify({
      [FAMILY]: Object.fromEntries(
        Object.entries(forms).map(([form, value]) => [form, hash(value)]),
      ),
    });

  function writeCatalog(forms) {
    mkdirSync(dirname(CATALOG), { recursive: true });
    writeFileSync(
      CATALOG,
      JSON.stringify({
        widget: Object.fromEntries(
          Object.entries(forms).map(([form, value]) => [
            `counts_${form}`,
            value,
          ]),
        ),
      }),
    );
  }

  // The refresh warnings print on stderr while the gate exits 0, so both
  // streams come back merged whatever the code was.
  function runGate(env, ...extraArgs) {
    const { status, stdout, stderr } = spawnSync(
      "node",
      ["scripts/check-i18n-keys.mjs", "--baseline", ...extraArgs],
      {
        cwd: ROOT,
        encoding: "utf8",
        env: { ...process.env, ...GATE_ENV, ...env },
      },
    );
    return { code: status ?? 1, out: `${stdout}${stderr}` };
  }

  afterEach(() => {
    rmSync(MODULE_DIR, { recursive: true, force: true });
    for (const path of tempFiles) rmSync(path, { force: true });
    tempFiles.length = 0;
  });

  const tempFiles = [];
  const tempPath = (label) => {
    const path = resolve(SANDBOX, `__plural_${label}.json`);
    tempFiles.push(path);
    return path;
  };

  it("is reported against the snapshot (the sisters kept the old wording)", () => {
    writeCatalog(NEW);
    const snap = tempPath("snap_partial");
    writeFileSync(snap, snapshotOf(OLD));

    const { code, out } = runGate({ I18N_PLURAL_SNAPSHOT: snap });

    expect(out).toContain(
      "SIBLINGS __i18n_plural_fixture__:widget.counts  (pl)  forms one,other changed, few,many kept the old wording",
    );
    expect(code).toBe(1);
    // The advice the reader is stopped with must name the exit that actually
    // refreshes the snapshot: a gate that sends the reader to a door it no
    // longer opens is worse than a gate without advice.
    expect(out).toContain("--write-plural-snapshot");
    expect(out).not.toContain("--write-baseline");
  });

  it("passes when the whole family moves together", () => {
    writeCatalog({
      ...OLD,
      ...NEW,
      few: "{{count}} zasoby",
      many: "{{count}} zasobów",
    });
    const snap = tempPath("snap_whole");
    writeFileSync(snap, snapshotOf(OLD));

    const { code, out } = runGate({ I18N_PLURAL_SNAPSHOT: snap });

    expect(out).not.toContain("SIBLINGS");
    expect(code).toBe(0);
  });

  it("says nothing about a family the snapshot has never seen", () => {
    writeCatalog(NEW);
    const snap = tempPath("snap_empty");
    writeFileSync(snap, "{}");

    const { code, out } = runGate({ I18N_PLURAL_SNAPSHOT: snap });

    expect(out).not.toContain("SIBLINGS");
    expect(code).toBe(0);
  });

  it("--write-baseline alone leaves the snapshot — and the finding — alone", () => {
    writeCatalog(NEW);
    const snap = tempPath("snap_keys_only");
    const baseline = tempPath("baseline_keys_only");
    writeFileSync(snap, snapshotOf(OLD));
    writeFileSync(baseline, JSON.stringify({ violations: [], unused: [] }));

    const first = runGate(
      { I18N_PLURAL_SNAPSHOT: snap, I18N_KEYS_BASELINE: baseline },
      "--write-baseline",
    );
    // Two artifacts forgive two unrelated things; refreshing the keys
    // baseline must not quietly refresh the plural snapshot with it.
    expect(first.out).not.toContain("SIBLINGS");
    expect(readFileSync(snap, "utf8")).toBe(snapshotOf(OLD));

    const second = runGate({ I18N_PLURAL_SNAPSHOT: snap });
    expect(second.out).toContain(
      "SIBLINGS __i18n_plural_fixture__:widget.counts",
    );
    expect(second.code).toBe(1);
  });

  it("--write-plural-snapshot takes the new state as the reference and says so", () => {
    writeCatalog(NEW);
    const snap = tempPath("snap_refresh");
    const baseline = tempPath("baseline_refresh");
    writeFileSync(snap, snapshotOf(OLD));
    writeFileSync(baseline, JSON.stringify({ violations: [], unused: [] }));

    const first = runGate(
      { I18N_PLURAL_SNAPSHOT: snap, I18N_KEYS_BASELINE: baseline },
      "--write-plural-snapshot",
    );
    expect(first.out).toContain(
      "SIBLINGS __i18n_plural_fixture__:widget.counts",
    );

    // The refresh absolves exactly what it printed, nothing more.
    const second = runGate({ I18N_PLURAL_SNAPSHOT: snap });
    expect(second.code).toBe(0);
  });

  it("--plural-report names the family that carries two vocabularies", () => {
    writeCatalog(NEW);
    // A second, well-behaved family: one noun bending around the number.
    writeFileSync(
      CATALOG,
      `${JSON.stringify({
        widget: {
          counts_one: NEW.one,
          counts_few: NEW.few,
          counts_many: NEW.many,
          counts_other: NEW.other,
          clean_one: "1 pozycja",
          clean_few: "{{count}} pozycje",
          clean_many: "{{count}} pozycji",
          clean_other: "{{count}} pozycji",
        },
      })}\n`,
    );

    const { code, out } = runGate(
      { I18N_PLURAL_SNAPSHOT: tempPath("snap_report") },
      "--plural-report",
    );

    expect(out).toContain("PLURAL-DRIFT __i18n_plural_fixture__:widget.counts");
    expect(out).not.toContain(":widget.clean");
    expect(code).toBe(0);
  });
});

describe("three dots in a catalogue string", () => {
  const MODULE_DIR = resolve(SANDBOX, "modules/__i18n_ellipsis_fixture__");
  const CATALOG = resolve(MODULE_DIR, "i18n/pl.json");

  function writeCatalog(value) {
    mkdirSync(dirname(CATALOG), { recursive: true });
    writeFileSync(
      CATALOG,
      `${JSON.stringify({ modal: { selectUnit: value } }, null, 2)}\n`,
    );
  }

  afterEach(() => {
    rmSync(MODULE_DIR, { recursive: true, force: true });
  });

  it("fails the run and names the key that carries them", () => {
    // 412 strings across the five languages spelled the ellipsis as three
    // periods when this rule was written — the same count in Polish as in
    // English, because the translation copied the source's character.
    writeCatalog("Wybierz jednostkę...");

    const { code, out } = runGate();

    expect(out).toContain(
      "ELLIPSIS pl/__i18n_ellipsis_fixture__.json  modal.selectUnit",
    );
    expect(out).toContain(
      "strings in the catalogues use three dots — `…` is a single character",
    );
    expect(code).toBe(1);
  });

  it("accepts the character, and counts a clean tree as clean", () => {
    writeCatalog("Wybierz jednostkę…");

    const { code, out } = runGate();

    expect(out).toContain(`0 strings with "..." instead of "…"`);
    expect(out).toContain("✓ no new violations");
    expect(code).toBe(0);
  });
});

describe("a screen name left in English", () => {
  const MODULE_DIR = resolve(SANDBOX, "modules/__i18n_title_fixture__");
  const VALUES = { en: "Summary", de: "Zusammenfassung", fr: "Résumé", es: "Resumen" };

  function writeCatalogs(key, pl) {
    for (const [lang, value] of Object.entries({ ...VALUES, pl })) {
      mkdirSync(join(MODULE_DIR, "i18n"), { recursive: true });
      writeFileSync(
        join(MODULE_DIR, `i18n/${lang}.json`),
        `${JSON.stringify({ panel: { [key]: value } }, null, 2)}\n`,
      );
    }
  }

  afterEach(() => {
    rmSync(MODULE_DIR, { recursive: true, force: true });
  });

  it("reports a bare title key left in English", () => {
    writeCatalogs("title", "Summary");

    const { code, out } = runGate();

    expect(out).toContain("panel.title");
    expect(out).toContain("the same string as in en");
    expect(code).toBe(1);
  });

  it("reports the suffix in the middle of a key as well (summary_title)", () => {
    writeCatalogs("summary_title", "Summary");

    const { code, out } = runGate();

    expect(out).toContain("panel.summary_title");
    expect(code).toBe(1);
  });

  it("reports a camelCase suffix (modalTitle)", () => {
    writeCatalogs("modalTitle", "Summary");

    const { code, out } = runGate();

    expect(out).toContain("panel.modalTitle");
    expect(code).toBe(1);
  });

  it("reports a plural form of a title key (title_one)", () => {
    writeCatalogs("bulk_title_one", "Summary");

    const { code, out } = runGate();

    expect(out).toContain("panel.bulk_title_one");
    expect(code).toBe(1);
  });

  it("passes once the Polish name is its own", () => {
    writeCatalogs("summary_title", "Podsumowanie");

    const { code } = runGate();

    expect(code).toBe(0);
  });
});

describe("a module's seeded category codes", () => {
  // A module's `CategoryDeclaration(code=...)` reaches the screen through
  // `categoryLabel` as `categories:codes.<code>`, so the shared catalogue has
  // to carry a name for it in all five languages. The fixture backend and
  // snapshot are pointed at the gate with the two env overrides, the same way
  // the plural snapshot is.
  const BACKEND_DIR = resolve(SANDBOX, "__i18n_backend_modules__");
  const MODULE_DIR = resolve(BACKEND_DIR, "widgets");
  const SNAPSHOT = resolve(SANDBOX, "__i18n_backend_keys__.json");

  function writeModule(code) {
    mkdirSync(MODULE_DIR, { recursive: true });
    writeFileSync(
      resolve(MODULE_DIR, "_module_declarations.py"),
      [
        "categories=[",
        "    CategoryDeclaration(",
        `        code='${code}',`,
        "        name='Fixture',",
        "        context_tag='widgets',",
        "    ),",
        "]",
        "",
      ].join("\n"),
    );
  }

  function runGate() {
    const { status, stdout, stderr } = spawnSync(
      "node",
      ["scripts/check-i18n-keys.mjs", "--baseline"],
      {
        cwd: ROOT,
        encoding: "utf8",
        env: {
          ...process.env,
          ...GATE_ENV,
          I18N_BACKEND_MODULES: BACKEND_DIR,
          I18N_BACKEND_KEYS: SNAPSHOT,
        },
      },
    );
    return { code: status ?? 1, out: `${stdout}${stderr}` };
  }

  afterEach(() => {
    rmSync(BACKEND_DIR, { recursive: true, force: true });
    rmSync(SNAPSHOT, { force: true });
  });

  it("refuses a seeded code no catalogue can translate", () => {
    writeModule("BRAND_NEW");
    writeFileSync(SNAPSHOT, JSON.stringify(["categories:codes.BRAND_NEW"]));

    const { code, out } = runGate();

    expect(out).toContain("MISSING categories:codes.BRAND_NEW");
    expect(code).toBe(1);
  });

  it("refuses a snapshot that missed a seeded code", () => {
    writeModule("BRAND_NEW");
    writeFileSync(SNAPSHOT, JSON.stringify([]));

    const { code, out } = runGate();

    expect(out).toContain("BACKEND-KEY ADDED   categories:codes.BRAND_NEW");
    expect(code).toBe(1);
  });

  it("passes when the code is in the snapshot and every catalogue", () => {
    writeModule("dairy");
    writeFileSync(SNAPSHOT, JSON.stringify(["categories:codes.dairy"]));

    const { code } = runGate();

    expect(code).toBe(0);
  });
});
