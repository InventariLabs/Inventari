import { describe, expect, it } from "vitest";
import formatWithoutLocale from "./format-without-locale.mjs";

const file = (text) => [{ path: "modules/things/ThingPage.tsx", text }];

describe("format-without-locale", () => {
  it("reports a number whose locale was spelled `undefined`", () => {
    const { findings } = formatWithoutLocale.run(
      file(`{total.toLocaleString(undefined, { maximumFractionDigits: 2 })}`),
    );

    expect(findings).toEqual(["modules/things/ThingPage.tsx:1"]);
  });

  it("reports the date and time spellings of the same mistake", () => {
    const { findings } = formatWithoutLocale.run(
      file(`const day = date.toLocaleDateString(undefined, { month: "short" });
const at = stamp.toLocaleTimeString(undefined, { hour: "2-digit" });`),
    );

    expect(findings).toEqual([
      "modules/things/ThingPage.tsx:1",
      "modules/things/ThingPage.tsx:2",
    ]);
  });

  it("reports every Intl constructor that leaves the language to the runtime", () => {
    for (const call of [
      "new Intl.NumberFormat(undefined, { style: 'percent' })",
      "new Intl.NumberFormat()",
      "new Intl.DateTimeFormat(undefined)",
      "new Intl.DateTimeFormat()",
      "new Intl.NumberFormat(navigator.language)",
    ]) {
      const { findings } = formatWithoutLocale.run(file(`const f = ${call};`));

      expect(findings, call).toEqual(["modules/things/ThingPage.tsx:1"]);
    }
  });

  it("reports navigator.language as the source of a toLocale* locale", () => {
    const { findings } = formatWithoutLocale.run(
      file(`const s = n.toLocaleString(navigator.language, { style: "percent" });`),
    );

    expect(findings).toEqual(["modules/things/ThingPage.tsx:1"]);
  });

  it("reports a call broken over several lines, on the line of the call", () => {
    const { findings } = formatWithoutLocale.run(
      file(`const a = 1;
const s = n.toLocaleString(
  undefined,
  { maximumFractionDigits: 2 },
);
const f = new Intl.NumberFormat(
  undefined,
  { style: "currency", currency: "PLN" },
);
const g = new Intl.DateTimeFormat(
);`),
    );

    expect(findings).toEqual([
      "modules/things/ThingPage.tsx:2",
      "modules/things/ThingPage.tsx:6",
      "modules/things/ThingPage.tsx:10",
    ]);
  });

  it("accepts an Intl constructor that names the reader's language", () => {
    const { findings } = formatWithoutLocale.run(
      file(`const f = new Intl.NumberFormat(i18n.language, { style: "percent" });
const g = new Intl.DateTimeFormat(
  locale,
  { month: "long" },
);
type T = Intl.DateTimeFormat;`),
    );

    expect(findings).toEqual([]);
  });

  it("leaves the time-zone read alone — a zone has no language in it", () => {
    const { findings } = formatWithoutLocale.run(
      file(`const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;`),
    );

    expect(findings).toEqual([]);
  });

  it("accepts a call that names the reader's language", () => {
    const { findings } = formatWithoutLocale.run(
      file(`const day = date.toLocaleDateString(i18n.language);
const total = formatNumberLocale(value, 2);`),
    );

    expect(findings).toEqual([]);
  });

  it("leaves a machine call with no locale at all alone", () => {
    // The stock-take CSV export writes a timestamp for a file, not a screen.
    const { findings } = formatWithoutLocale.run(
      file(`const stamp = iso ? new Date(iso).toLocaleString() : "";`),
    );

    expect(findings).toEqual([]);
  });

  it("does not report the mistake written about in a comment", () => {
    const { findings } = formatWithoutLocale.run(
      file(`// The row used to call value.toLocaleString(undefined, { … }).
const label = formatNumberLocale(value, 1);`),
    );

    expect(findings).toEqual([]);
  });
});
