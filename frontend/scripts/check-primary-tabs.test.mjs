/**
 * The gate has to go red on the call site it was written after — tabs assembled
 * from a network collection — and stay quiet on the fixed sets every other
 * list legitimately uses.
 */
import { describe, expect, it } from "vitest";

import { findingsIn, isScanned } from "./check-primary-tabs.mjs";

const rules = (text) => findingsIn("x.tsx", text).map((f) => f.rule);

// The inventory report's storage picker, as it stood before the fix: a tab per
// storage, fetched over the wire.
const NETWORK_TABS_FIXTURE = `
export function InventoryReportControls({ storages, storageFilter, onStorageFilterChange }) {
  return (
    <ListControlBar
      primaryTabs={{
        value: storageFilter,
        onChange: onStorageFilterChange,
        options: [
          { value: "", label: t("stats:inventoryReport.allStorages") },
          ...(storages ?? []).map((storage) => ({
            value: storage.id,
            label: storage.name,
          })),
        ],
      }}
    />
  );
}
`;

describe("check-primary-tabs", () => {
  it("rejects tabs spread from a coalesced variable", () => {
    expect(rules(NETWORK_TABS_FIXTURE)).toEqual(["network-tabs"]);
  });

  it("allows literal options", () => {
    expect(
      rules(`
        primaryTabs={{
          value: tab,
          onChange: setTab,
          options: [
            { value: "active", label: t("active") },
            { value: "archived", label: t("archived") },
          ],
        }}
      `),
    ).toEqual([]);
  });

  it("allows options mapped from a module constant", () => {
    expect(
      rules(`
        const STATUS_TABS = ["open", "done"];
        primaryTabs={{
          value: status,
          onChange: setStatus,
          options: STATUS_TABS.map((tab) => ({ value: tab, label: tab })),
        }}
      `),
    ).toEqual([]);
  });

  it("leaves spreads outside primaryTabs alone", () => {
    expect(
      rules(`
        <SomePanel
          items={[
            { id: "fixed" },
            ...(extras ?? []).map((x) => ({ id: x.id })),
          ]}
        />
      `),
    ).toEqual([]);
  });

  it("skips test files", () => {
    expect(isScanned("components/X.tsx")).toBe(true);
    expect(isScanned("components/X.test.tsx")).toBe(false);
    expect(isScanned("components/X.md")).toBe(false);
  });
});
