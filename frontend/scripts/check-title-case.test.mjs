import { describe, expect, it } from "vitest";

import { findingsOf, isTitleCase } from "./check-title-case.mjs";

describe("Title Case in a catalog", () => {
  it.each([
    "Create Return",
    "Picking Complete",
    "Document Totals",
    "Send to Vendor",
    "Select the From location",
    "Create Correction ({{count}} lines)",
    "{{count}} Line Items",
  ])("flags %j", (value) => {
    expect(isTitleCase(value)).toBe(true);
  });

  it.each([
    "Create return",
    "Document register",
    "Export CSV",
    "Download PDF",
    "Stock",
    "Receive delivery from {{subject}}",
    "Not a Title Case sentence, though. It has a full stop.",
    "Fill in the quantity, the unit and the Batch Number of every line",
  ])("leaves %j alone", (value) => {
    expect(isTitleCase(value)).toBe(false);
  });

  it("keys a finding by file and path", () => {
    expect(
      findingsOf("src/modules/x/i18n/en.json", {
        a: { title: "Purchase Orders", ok: "Purchase orders" },
      }),
    ).toEqual({ "src/modules/x/i18n/en.json::a.title": "Purchase Orders" });
  });
});
