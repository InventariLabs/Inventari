import { describe, expect, it } from "vitest";

import en from "../i18n/en.json";
import pl from "../i18n/pl.json";
import de from "../i18n/de.json";
import fr from "../i18n/fr.json";
import es from "../i18n/es.json";

/**
 * Regression guard.
 *
 * PurchaseOrderListItem / POActionBar / PurchaseOrdersPage render the PO
 * status via `t("status.${po.status}")`. If a status key is missing from the
 * module catalog, i18next falls back to the raw key (`status.DRAFT`), which
 * leaks into the UI. The test i18n mock masks this by falling back across
 * namespaces (the key exists in `warehouse`), so a render-only test cannot
 * catch it — the catalog itself must be asserted.
 */

const PO_STATUSES = [
  "DRAFT",
  "PENDING_APPROVAL",
  "CONFIRMED",
  "COMPLETED",
  "CANCELLED",
] as const;

type Catalog = Record<string, unknown>;

const catalogs: Record<string, Catalog> = {
  en: en as unknown as Catalog,
  pl: pl as unknown as Catalog,
  de: de as unknown as Catalog,
  fr: fr as unknown as Catalog,
  es: es as unknown as Catalog,
};

function flatKeys(node: unknown, prefix: string[] = []): string[] {
  if (node == null) return [];
  if (typeof node === "string") return [prefix.join(".")];
  if (typeof node === "object") {
    return Object.entries(node as Catalog).flatMap(([k, v]) =>
      flatKeys(v, [...prefix, k]),
    );
  }
  return [];
}

describe("purchase_orders — PO status labels present in all 5 languages", () => {
  for (const [lang, catalog] of Object.entries(catalogs)) {
    it(`${lang} defines status.${PO_STATUSES.join(", status.")}`, () => {
      const keys = new Set(flatKeys(catalog));
      for (const status of PO_STATUSES) {
        expect(keys).toContain(`status.${status}`);
      }
    });
  }
});
