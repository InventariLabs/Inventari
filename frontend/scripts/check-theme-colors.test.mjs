/**
 * The gate has to fail on exactly the shape that shipped for months: a
 * numeric status class whose ramp the theme never defined, compiling to no
 * CSS rule while every gate stayed green. Measured dead on a running stack
 * before this gate existed: `text-warning-600` and `text-warning-400` both
 * rendered the body colour, and the contrast gate — which reads tokens, not
 * class names — could not see it.
 *
 * The palette here is the real resolved one (defaults + tailwind.config.js),
 * so the tests also pin what must KEEP working: `text-red-600` survives the
 * config's partial override of `red`, and `text-on-warning` is the sanctioned
 * token pair half.
 */
import { describe, expect, it } from "vitest";

import { findingsIn } from "./check-theme-colors.mjs";

const rules = (text) => findingsIn("x.tsx", text).map((f) => f.rule);

describe("check-theme-colors — a colour the theme never defines", () => {
  it("rejects the measured-dead warning classes", () => {
    expect(rules('<p className="text-xs text-warning-600">warn</p>')).toEqual([
      "no-such-color",
    ]);
    expect(
      rules(
        '<p className="text-xs text-warning-600 dark:text-warning-400">w</p>',
      ),
    ).toEqual(["no-such-color", "no-such-color"]);
  });

  it("rejects every dead status ramp, in every colour-bearing utility", () => {
    expect(rules('<p className="text-danger-600">err</p>')).toEqual([
      "no-such-color",
    ]);
    expect(rules('<span className="bg-warning-50">tint</span>')).toEqual([
      "no-such-color",
    ]);
    expect(rules('<div className="border-info-500">edge</div>')).toEqual([
      "no-such-color",
    ]);
    expect(rules('<div className="ring-danger-500">focus</div>')).toEqual([
      "no-such-color",
    ]);
  });

  it("rejects a planted violation inside a conditional class list", () => {
    expect(rules('empty ? "text-warning-600" : "text-on-muted"')).toEqual([
      "no-such-color",
    ]);
  });

  it("rejects a bare status name — no ramp, no bare colour, compiles to nothing", () => {
    expect(
      rules('<p role="alert" className="text-sm text-danger">e</p>'),
    ).toEqual(["no-such-color"]);
    expect(rules('<span className="bg-warning">w</span>')).toEqual([
      "no-such-color",
    ]);
    expect(rules('<div className="border-info">x</div>')).toEqual([
      "no-such-color",
    ]);
    expect(rules('<div className="ring-error">x</div>')).toEqual([
      "no-such-color",
    ]);
    expect(rules('<Button className="hover:text-danger">x</Button>')).toEqual([
      "no-such-color",
    ]);
  });

  it("rejects a bare status name behind a side or offset prefix", () => {
    // The prefix is stripped to judge a numeric step, and the bare-name
    // branch then saw "l-danger" instead of "danger" and let it through —
    // hidden only because no file wrote one yet.
    for (const cls of [
      "border-l-danger",
      "border-x-danger",
      "border-t-warning",
      "border-e-info",
      "ring-offset-danger",
      "border-l-error/50",
    ]) {
      expect(rules(`<div className="${cls}">x</div>`)).toEqual([
        "no-such-color",
      ]);
    }
  });

  it("still lets a prefixed class through that names no status", () => {
    expect(rules('<div className="border-l-primary-500">x</div>')).toEqual([]);
    expect(rules('<div className="border-l-4 ring-offset-2">x</div>')).toEqual(
      [],
    );
    expect(rules('<div className="border-l-border">x</div>')).toEqual([]);
  });

  it("rejects a bare status name with an opacity modifier", () => {
    expect(rules('<div className="bg-danger/50">x</div>')).toEqual([
      "no-such-color",
    ]);
  });

  it("keeps the ambiguity exception for bare names outside the status set", () => {
    expect(rules('<p className="text-center text-primary">x</p>')).toEqual([]);
  });

  it("rejects a step the ramp does not define — it compiles to nothing too", () => {
    expect(rules('<p className="text-primary-999">x</p>')).toEqual([
      "no-such-step",
    ]);
    expect(rules('<p className="bg-success-950">x</p>')).toEqual([
      "no-such-step",
    ]);
  });

  it("rejects a dead colour on a border side — the width prefix is not an excuse", () => {
    expect(rules('<div className="border-l-warning-500">x</div>')).toEqual([
      "no-such-color",
    ]);
  });
});

describe("check-theme-colors — what must keep working", () => {
  it("allows the sanctioned on-* tokens, bare and compound", () => {
    expect(rules('<span className="text-on-warning">w</span>')).toEqual([]);
    expect(
      rules('<span className="bg-red-100 text-on-danger">d</span>'),
    ).toEqual([]);
    expect(rules('<span className="text-on">body</span>')).toEqual([]);
  });

  it("allows defined ramps, including steps inherited from the default palette", () => {
    expect(rules('<p className="text-red-600">x</p>')).toEqual([]);
    expect(rules('<p className="bg-red-100 text-on-danger">x</p>')).toEqual([]);
    expect(rules('<p className="text-success-600">x</p>')).toEqual([]);
    expect(rules('<div className="border-primary-500">x</div>')).toEqual([]);
    expect(rules('<div className="bg-gray-50">x</div>')).toEqual([]);
  });

  it("stays quiet on non-colour utilities and arbitrary values", () => {
    expect(
      rules('<p className="text-sm text-[10px] text-center">x</p>'),
    ).toEqual([]);
    expect(rules('<p className="text-2xl font-semibold">x</p>')).toEqual([]);
    expect(rules('<div className="bg-cover border-2 ring-1">x</div>')).toEqual(
      [],
    );
    expect(rules('<div className="text-[var(--local-token)]">x</div>')).toEqual(
      [],
    );
  });

  it("stays quiet on width utilities sharing the border/ring prefix", () => {
    expect(
      rules(
        '<div className="border-b-2 border-l-4 border-b-0 border-spacing-y-0 ring-offset-2">',
      ),
    ).toEqual([]);
  });

  it("judges a colour on a border side, not the side itself", () => {
    expect(rules('<div className="border-t-primary-600">x</div>')).toEqual([]);
    expect(rules('<div className="border-l-accent-500">x</div>')).toEqual([]);
    expect(rules('<div className="border-b-gray-100">x</div>')).toEqual([]);
  });

  it("stays quiet on a prose fragment in a comment", () => {
    expect(rules("// the text-on-* half of each pair")).toEqual([]);
  });

  it("stays quiet on interpolation the scanner cannot resolve", () => {
    expect(rules("const cls = `text-${name}-600`;")).toEqual([]);
  });
});
