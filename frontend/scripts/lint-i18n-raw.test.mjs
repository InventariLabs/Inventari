/**
 * A gate nobody can make fail is a gate nobody can trust.
 *
 * Each case below plants one shape of the class `lint-i18n-raw` exists for —
 * the three that were once its declared blind spots (a JSX text node, a label
 * literal in an option table, English glued onto a `t()` inside a template)
 * and one that was never in doubt (a bare toast argument). The negative cases
 * beside them are the boundaries: the tree is full of names and symbols that
 * are the same in every language, and a rule that flags `Inventari` or a URL
 * is a rule that gets switched off the first week it is red.
 */
import { describe, expect, it } from "vitest";
import { findViolations } from "./lint-i18n-raw.mjs";

const component = (text) => [{ path: "src/pages/Planted.tsx", text }];
const module_ = (text) => [{ path: "src/pages/Planted.ts", text }];

describe("lint-i18n-raw", () => {
  it("flags a JSX text node written in prose", () => {
    const findings = findViolations(
      component(`export const A = () => <span>Active list</span>;`),
    );
    expect(findings).toHaveLength(1);
    expect(findings[0]).toContain("Active list");
  });

  it("flags a single word a reader still has to read", () => {
    const findings = findViolations(
      component(`export const A = () => <span>Yes</span>;`),
    );
    expect(findings).toHaveLength(1);
  });

  it("leaves a product name, a unit and an entity alone", () => {
    expect(
      findViolations(
        component(
          `export const A = () => (
             <p>Inventari &middot; <span>kcal</span> <span>Open Food Facts</span></p>
           );`,
        ),
      ),
    ).toHaveLength(0);
  });

  it("flags a label literal in a module-scope table of options", () => {
    const findings = findViolations(
      component(
        `const PRESETS = [{ name: "Small (38x15)", width: 38, height: 15 }] as const;`,
      ),
    );
    expect(findings).toHaveLength(1);
    expect(findings[0]).toContain("Small (38x15)");
  });

  it("leaves a third-party service descriptor alone — its name is its own", () => {
    expect(
      findViolations(
        component(
          `const PROVIDERS = [{ id: "openai", name: "OpenAI", docsUrl: "https://example.test" }];`,
        ),
      ),
    ).toHaveLength(0);
  });

  it("leaves a technical identifier in a label field alone", () => {
    expect(
      findViolations(component(`const A = [{ name: "announcements" }];`)),
    ).toHaveLength(0);
  });

  it("flags English glued onto a t() interpolation", () => {
    const findings = findViolations(
      module_(`const m = (t, q) => \`\${t("items:consumed")} (\${q} left)\`;`),
    );
    expect(findings).toHaveLength(1);
    expect(findings[0]).toContain("left)");
  });

  it("leaves a URL built around a t() interpolation alone", () => {
    expect(
      findViolations(
        module_("const u = (t, host) => `${t('items:proto')}//${host}/api`;"),
      ),
    ).toHaveLength(0);
  });

  it("still flags a bare string passed to a toast", () => {
    const findings = findViolations(
      component(`toast.success("Saved the thing");`),
    );
    expect(findings).toHaveLength(1);
  });

  it("does not read a test file's English as shipped UI", () => {
    expect(
      findViolations([
        {
          path: "src/pages/Planted.test.tsx",
          text: `expect(screen.getByText("Active list")).toBeTruthy();`,
        },
      ]),
    ).toHaveLength(0);
  });
});
