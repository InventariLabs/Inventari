/**
 * The policy the application's own origin ships with.
 *
 * `script-src 'unsafe-inline'` was the weakest link in the stack: the API
 * answers with a strict policy of its own and Caddy adds HSTS, while the
 * origin serving the app trusted any inline script on the page. The build
 * emits none — every <script> in the built index.html carries a src,
 * including the service-worker registration — so the allowance bought
 * nothing and only gave an injected one a way to run.
 *
 * A config file has no type checker and no linter, which is exactly why the
 * line is worth pinning here.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const conf = readFileSync(resolve(__dirname, "../../nginx.conf"), "utf8");
const policy =
  /add_header Content-Security-Policy "([^"]+)"/.exec(conf)?.[1] ?? "";

function directive(name: string): string {
  const found = policy
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${name} `));
  return found ?? "";
}

describe("the SPA origin's Content-Security-Policy", () => {
  it("is declared at all", () => {
    expect(policy).not.toBe("");
  });

  it("does not trust inline script", () => {
    expect(directive("script-src")).toBe("script-src 'self'");
  });

  it("still allows inline style, which React writes as attributes", () => {
    // Moving the hole from scripts to styles is renaming it, not closing it.
    expect(directive("style-src")).toContain("'unsafe-inline'");
  });

  it("closes the two ways an injection routes around script-src", () => {
    // A planted <base> retargets every relative script URL; <object> and
    // <embed> execute outside script-src entirely.
    expect(directive("base-uri")).toBe("base-uri 'self'");
    expect(directive("object-src")).toBe("object-src 'none'");
  });

  it("never allows eval", () => {
    expect(policy).not.toContain("unsafe-eval");
  });
});
