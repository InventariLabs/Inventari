/**
 * What a visitor sees before any script has run. A first open on a phone
 * network waits seconds for the bundle, and an empty `#root` is a white page
 * with nothing to say the address was right: the document itself carries the
 * sign, and React replaces it on its first render.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const html = readFileSync(resolve(__dirname, "../../index.html"), "utf8");
const page = new DOMParser().parseFromString(html, "text/html");
const root = page.getElementById("root");

describe("the document before the application loads", () => {
  it("says it is loading and names the product, in the root React replaces", () => {
    expect(root?.querySelector('[role="status"]')).not.toBeNull();
    expect(root?.textContent).toContain("Inventari");
  });

  it("is not a bright page on a dark system", () => {
    expect(html).toMatch(/prefers-color-scheme:\s*dark/);
  });

  it("styles nothing but the sign, so no rule outlives it", () => {
    const selectors = (page.querySelector("style")?.textContent ?? "")
      .replace(/@keyframes[^{]+\{[^}]*\{[^}]*\}\s*\}/g, "")
      .replace(/@media[^{]+\{/g, "")
      .match(/[^{}\s][^{}]*(?=\{)/g);
    expect(selectors?.length).toBeGreaterThan(0);
    for (const selector of selectors ?? []) {
      expect(selector).toMatch(/^\.boot\b/);
    }
  });

  it("carries no inline script, which the origin's policy would refuse", () => {
    const inline = [...page.querySelectorAll("script")].filter((s) => !s.src);
    expect(inline).toEqual([]);
  });
});
