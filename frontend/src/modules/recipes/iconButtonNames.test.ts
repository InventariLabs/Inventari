import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

/**
 * A `<Button>` whose whole content is an icon has no text for the
 * accessibility tree to read, so without `aria-label` it announces as
 * "button" and nothing else. Instances of this kept coming back in the same
 * module, which is what a gate is for.
 *
 * `title` alone is not enough: it is the last resort of the accessible-name
 * algorithm, it is not announced consistently, and it never appears on a touch
 * screen. The convention is both — `aria-label` names the control, `title`
 * gives the pointer user the same words (UI_GUIDELINES §11.4).
 */
const MODULE_ROOT = join(__dirname);

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    if (!path.endsWith(".tsx") || path.endsWith(".test.tsx")) return [];
    return [path];
  });
}

/**
 * Index of the `>` closing an opening tag. Scanning for the character alone
 * finds the one inside `onClick={() => …}` — every handler is an arrow — so
 * brace depth has to be tracked.
 */
function tagEnd(source: string, from: number): number {
  let depth = 0;
  for (let i = from; i < source.length; i++) {
    const char = source[i];
    if (char === "{") depth++;
    else if (char === "}") depth--;
    else if (char === ">" && depth === 0) return i;
  }
  return -1;
}

/**
 * Whether anything survives once icon elements, element-only expressions and
 * comments are gone.
 *
 * The scan is brace-balanced — a regex over `[^{}]*` cannot see past
 * `size={16}`. Inside an expression, JSX elements are stripped first; what
 * then decides is the residue: a husk like `{isPending ? : }` (both branches
 * were icons) is dropped, while an expression with a text branch — the
 * `{isPending ? <Loader2 /> : t(…)}` shape — keeps its call and counts as
 * labelled. Removing self-closing tags *before* classifying the ternary (the
 * original order) hollowed it out and let a nameless save button pass the
 * gate. (No literal translation calls in this comment on purpose: the global
 * i18n key scan regexes call-shaped strings out of comments as if they were
 * code.)
 *
 * Blind spot, documented: an icon-only button whose content sits in a nested
 * component (`<Button><AvailabilityBadge /></Button>`) is invisible to a
 * single-file scan — those instances are fixed by review, not by this gate.
 */
function stripJsxElements(source: string): string {
  return source
    .replace(/<[A-Za-z][\w.]*(?:"[^"]*"|'[^']*'|\{[^{}]*\}|[^>"'{])*\/>/gs, "")
    .replace(/<\/?>/g, "")
    .replace(/<\/?[A-Za-z][^>]*>/gs, "");
}

function hasVisibleLabel(body: string): boolean {
  let kept = "";
  for (let i = 0; i < body.length; i++) {
    if (body[i] === "{") {
      let depth = 1;
      let j = i + 1;
      while (j < body.length && depth > 0) {
        if (body[j] === "{") depth++;
        else if (body[j] === "}") depth--;
        j++;
      }
      const inner = stripJsxElements(body.slice(i + 1, j - 1));
      // A branch zone (after the first `?`/`&&`) with no identifier left once
      // the element is stripped and keywords removed rendered an icon, not
      // text: `{isPending ? <Loader2 /> : <Check />}` → `isPending ? : ` →
      // husk. `{c ? parsingText : submitText}` keeps its identifiers → text.
      const isHusk = (() => {
        if (!/(\?|&&)/.test(inner)) return false;
        if (/["'`]/.test(inner)) return false;
        const branchZone = inner.replace(/^[\s\S]*?(?:\?|&&)/, "");
        const residue = branchZone.replace(
          /\b(?:null|undefined|true|false)\b/g,
          "",
        );
        return !/[A-Za-z_$]/.test(residue);
      })();
      if (!isHusk) kept += inner;
      i = j - 1;
    } else {
      kept += body[i];
    }
  }
  return (
    kept
      .replace(
        /<[A-Za-z][\w.]*(?:"[^"]*"|'[^']*'|\{[^{}]*\}|[^>"'{])*\/>/gs,
        "",
      )
      .replace(/<\/?[A-Za-z][^>]*>/gs, "")
      .replace(/\{\/\*.*?\*\/\}/gs, "")
      .trim().length > 0
  );
}

function unnamedIconButtons(path: string): string[] {
  const source = readFileSync(path, "utf8");
  const found: string[] = [];
  let cursor = 0;
  for (;;) {
    const start = source.indexOf("<Button", cursor);
    if (start === -1) break;
    const end = tagEnd(source, start);
    if (end === -1) break;
    const tag = source.slice(start, end);
    const closing = source.indexOf("</Button>", end);
    const body =
      source[end - 1] === "/" || closing === -1
        ? ""
        : source.slice(end + 1, closing);
    if (!hasVisibleLabel(body) && !/\baria-label=/.test(tag)) {
      const line = source.slice(0, start).split("\n").length;
      found.push(`${path.replace(MODULE_ROOT, "")}:${line}`);
    }
    cursor = end;
  }
  return found;
}

/**
 * Icons inside a button are 16px (UI_GUIDELINES §11.4). The module had eight
 * different sizes between 8 and 20, which reads as noise at a glance: the same
 * action is a different weight depending on which screen it sits on. Icons
 * standing on their own — a hero glyph, an empty-state illustration — are not
 * covered by the rule and keep their own scale.
 */
function offSizeIconsInButtons(path: string): string[] {
  const source = readFileSync(path, "utf8");
  const found: string[] = [];
  let cursor = 0;
  for (;;) {
    const start = source.indexOf("<Button", cursor);
    if (start === -1) break;
    const end = tagEnd(source, start);
    if (end === -1) break;
    const closing =
      source[end - 1] === "/" ? -1 : source.indexOf("</Button>", end);
    const region =
      closing === -1
        ? source.slice(start, end + 1)
        : source.slice(start, closing);
    for (const match of region.matchAll(/size=\{(\d+)\}/g)) {
      if (match[1] === "16") continue;
      const line = source
        .slice(0, start + (match.index ?? 0))
        .split("\n").length;
      found.push(
        `${path.replace(MODULE_ROOT, "")}:${line} → size={${match[1]}}`,
      );
    }
    cursor = end;
  }
  return found;
}

describe("recipes icon buttons", () => {
  it("finds source files at all (the gate is not vacuous)", () => {
    expect(sourceFiles(MODULE_ROOT).length).toBeGreaterThan(50);
  });

  it("gives every icon-only button an accessible name", () => {
    expect(sourceFiles(MODULE_ROOT).flatMap(unnamedIconButtons)).toEqual([]);
  });

  it("sizes every icon inside a button at 16", () => {
    expect(sourceFiles(MODULE_ROOT).flatMap(offSizeIconsInButtons)).toEqual([]);
  });
});
