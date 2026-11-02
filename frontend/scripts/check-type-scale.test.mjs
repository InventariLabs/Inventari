/**
 * The gate has to fail on the things that got past everyone for a year, and
 * stay quiet on the two roles that legitimately look like violations.
 */
import { describe, expect, it } from "vitest";

import { findingsIn, isScanned } from "./check-type-scale.mjs";

const rules = (text) => findingsIn("x.tsx", text).map((f) => f.rule);

describe("check-type-scale — sizes", () => {
  it("rejects a size below the floor", () => {
    expect(rules('<p className="text-[7px] text-on-muted">kcal</p>')).toEqual([
      "size",
    ]);
  });

  it("rejects a size that is on no scale", () => {
    expect(rules('<p className="text-[13px]">Announcement</p>')).toEqual([
      "size",
    ]);
    expect(rules('<p className="text-[11px]">Tag</p>')).toEqual(["size"]);
  });

  it("allows the micro-label token", () => {
    expect(rules('<p className="text-[10px] font-medium">SKU</p>')).toEqual([]);
  });

  it("allows every Tailwind step", () => {
    expect(
      rules('<h1 className="text-xl font-semibold">Products</h1>'),
    ).toEqual([]);
  });
});

describe("check-type-scale — weights", () => {
  it("rejects a title weight on a label size", () => {
    expect(
      rules('<span className="text-xs font-semibold">Status</span>'),
    ).toEqual(["weight-small"]);
    expect(
      rules('<span className="text-[10px] font-semibold">Status</span>'),
    ).toEqual(["weight-small"]);
  });

  it("rejects font-bold anywhere in the interface", () => {
    expect(rules('<h2 className="text-lg font-bold">Total</h2>')).toEqual([
      "weight-bold",
    ]);
  });

  it("leaves a monospace code alone — there weight is the only signal", () => {
    expect(
      rules(
        '<span className="font-mono text-[10px] font-bold">STM-4021</span>',
      ),
    ).toEqual([]);
  });

  it("accepts the record-name token", () => {
    expect(
      rules('<p className="text-sm font-semibold text-on">Butter</p>'),
    ).toEqual([]);
  });

  it("sees a class list built as a template literal, not just a plain string", () => {
    // The conditional class is where drift hides, and a scan that only reads
    // string literals walks straight past it.
    const line = "className={`text-xs ${active ? 'font-semibold' : ''}`}";
    expect(rules(line)).toEqual(["weight-small"]);
  });
});

describe("check-type-scale — what it scans", () => {
  it("skips its own tests and the test tree", () => {
    expect(isScanned("components/ui/Badge.test.tsx")).toBe(false);
    expect(isScanned("components/ui/Badge.tsx")).toBe(true);
    expect(isScanned("utils/helpers.ts")).toBe(true);
    expect(isScanned("styles/app.css")).toBe(false);
  });
});

describe("check-type-scale — size and weight written apart", () => {
  it("finds a title weight whose size sits on the parent element", () => {
    // The pagination did exactly this: `text-xs` on the wrapper, and
    // `font-semibold` on the span inside it holding the count.
    const src = [
      '<p className="text-xs text-on-muted">',
      "  Showing",
      '  <span className="font-semibold text-on tabular-nums">1–50</span>',
    ].join("\n");
    expect(findingsIn("x.tsx", src).map((f) => f.rule)).toEqual([
      "weight-small",
    ]);
  });

  it("does not reach back past its window", () => {
    const src = [
      '<p className="text-xs">',
      "  a",
      "  b",
      "  c",
      '  <span className="font-semibold">Title</span>',
    ].join("\n");
    expect(findingsIn("x.tsx", src)).toEqual([]);
  });
});
