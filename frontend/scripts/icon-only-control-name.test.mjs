/**
 * The local jsx-a11y rule that refuses a button holding nothing but an icon
 * and no accessible name. Runs the project's real ESLint config over inline
 * markup, so the rule, its registration in the jsx-a11y block and the
 * baseline's relaxation list are all exercised together.
 */
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = process.cwd(); // vitest runs from frontend/
const RULE = "jsx-a11y/icon-only-control-name";

// A child `eslint` process rather than the ESLint API: eslint.config.js
// resolves its JSON files through import.meta.url, which vitest rewrites.
function findings(markup) {
  const code = `import { X } from "lucide-react";\nexport const C = () => (<div>${markup}</div>);\n`;
  const run = spawnSync(
    "npx",
    [
      "eslint",
      "--stdin",
      "--stdin-filename",
      resolve(ROOT, "src/components/ui/__icon_only_probe.tsx"),
      "-f",
      "json",
    ],
    { cwd: ROOT, input: code, encoding: "utf8" },
  );
  const [result] = JSON.parse(run.stdout);
  return result.messages.filter((m) => m.ruleId === RULE);
}

describe("jsx-a11y/icon-only-control-name", () => {
  it("refuses a <button> that holds only an icon", () => {
    expect(findings("<button onClick={f}><X size={14} /></button>")).toHaveLength(1);
  });

  it("refuses the shared <Button> that holds only an icon", () => {
    expect(
      findings("<Button size=\"icon\">\n  <X />\n</Button>"),
    ).toHaveLength(1);
  });

  it("accepts aria-label, aria-labelledby and title", () => {
    for (const attr of ['aria-label="Close"', 'aria-labelledby="h"', 'title="Close"']) {
      expect(findings(`<button ${attr}><X /></button>`)).toHaveLength(0);
    }
  });

  it("accepts a button with visible text, an expression or a spread", () => {
    expect(findings("<button><X />Close</button>")).toHaveLength(0);
    expect(findings("<button><X />{label}</button>")).toHaveLength(0);
    expect(findings("<button {...props}><X /></button>")).toHaveLength(0);
  });

  it("accepts a nested element with content, such as an sr-only span", () => {
    expect(
      findings('<button><X /><span className="sr-only">Close</span></button>'),
    ).toHaveLength(0);
  });
});
