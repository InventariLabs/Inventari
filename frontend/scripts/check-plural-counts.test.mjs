/**
 * The scanner decides the verdict, so these pin what it has to tell apart:
 * a count pasted next to a translated noun, a hand-written plural rule, and
 * the two shapes that look similar and are not the defect -- a ratio, and a
 * non-numeric value read out next to a label.
 */
import { describe, expect, it } from "vitest";

import { isScanned, pastedCountsIn } from "./check-plural-counts.mjs";

const lines = (text) => pastedCountsIn("a.tsx", text).map((f) => f.line);

describe("pastedCountsIn", () => {
  it("reports a count pasted next to a translated noun", () => {
    expect(
      lines('const s = `${locationCount} ${t("locations:locations")}`;'),
    ).toEqual([1]);
  });

  it("reports a length pasted next to one", () => {
    expect(lines('`${rows.length} ${t("import.rows")}`')).toEqual([1]);
  });

  it("reports a plural rule written into the component", () => {
    // The form the dashboard tile carried: one language's grammar as a
    // ternary, which is wrong wherever there are more than two forms.
    const text =
      '`${n} ${n === 1 ? t("dashboard.location") : t("dashboard.locations")}`';
    expect(lines(text)).toEqual([1]);
  });

  it("accepts a count that goes through t() with count", () => {
    expect(lines('`${t("dashboard.locationCount", { count: n })}`')).toEqual(
      [],
    );
  });

  it("leaves a non-numeric value next to a label alone", () => {
    // `${reason} ${t("reorg.deleteLiftsChildren")}` is a sentence, not a
    // count, and has no plural form to select.
    expect(lines('`${reason} ${t("locations:reorg.lifts")}`')).toEqual([]);
  });

  it("reports the line the paste is on, not the first line of the file", () => {
    expect(lines(["const a = 1;", '`${total} ${t("x")}`'].join("\n"))).toEqual([
      2,
    ]);
  });

  it("reports the brace spelling of the same paste", () => {
    // `{totalRows} {t("warehouse:import.rows")}` renders "1 wierszy", and
    // the same shape two lines below rendered "1 błędów" — while the
    // scanner, which read template literals only, passed both.
    expect(
      lines('<span>{totalRows} {t("warehouse:import.rows")}</span>'),
    ).toEqual([1]);
    expect(
      lines(
        '<span>{result.errors.length} {t("warehouse:import.errors")}</span>',
      ),
    ).toEqual([1]);
  });

  it("leaves a ratio's denominator alone in the brace spelling too", () => {
    expect(
      lines('<span>{available}/{total} {t("stockCoverage.label")}</span>'),
    ).toEqual([]);
    expect(
      lines(
        '<Badge>{stats.purchased} / {stats.total} {t("detail.purchased")}</Badge>',
      ),
    ).toEqual([]);
  });

  it("leaves a unit symbol alone, which reads the same after every number", () => {
    // "szt." does not inflect, and the catalogue keeps unit symbols under
    // `units.` for exactly that reason.
    expect(
      lines('<Badge>{stat.items_count} {t("common:units.pcs")}</Badge>'),
    ).toEqual([]);
  });

  it("accepts the brace spelling that goes through t() with count", () => {
    expect(
      lines(
        '<span>{t("warehouse:import.rowCount", { count: totalRows })}</span>',
      ),
    ).toEqual([]);
  });
});

describe("isScanned", () => {
  it("reads components and the hooks beside them", () => {
    expect(isScanned("modules/spaces/pages/StorageZonePage.tsx")).toBe(true);
    expect(isScanned("hooks/useHeader.ts")).toBe(true);
  });

  it("skips the tests, which quote the defect on purpose", () => {
    expect(isScanned("modules/spaces/pages/StorageZonePage.test.tsx")).toBe(
      false,
    );
    expect(isScanned("scripts/x.mjs")).toBe(false);
  });
});
