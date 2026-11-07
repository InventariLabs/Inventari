import { describe, expect, it } from "vitest";
import { findViolations } from "./check-empty-state.mjs";

const page = (text, path = "modules/things/pages/ThingListPage.tsx") => [
  { path, text },
];

describe("check-empty-state", () => {
  it("catches a page empty state with no description at all", () => {
    const findings = findViolations(
      page(`<EmptyState icon={Box} title={t("empty.title")} />`),
    );
    expect(findings.length).toBe(1);
    expect(findings[0]).toContain("ThingListPage.tsx:1");
  });

  it("catches a page empty state with icon and action but no description", () => {
    const findings = findViolations(
      page(`<EmptyState
  icon={MapPin}
  title={t("locationsPage.empty")}
  primaryAction={<EmptyStateAction label={t("locations.addTitle")} />}
/>`),
    );
    expect(findings.length).toBe(1);
  });

  it("counts every empty state of a page, not just the first", () => {
    const findings = findViolations(
      page(`<>
  <EmptyState icon={Archive} title={t("items:archivedNoMatches")} />
  <EmptyState
    icon={Archive}
    title={t("items:noArchivedItems")}
    description={t("items:noArchivedItemsDesc")}
  />
</>`),
    );
    expect(findings.length).toBe(1);
  });

  it("passes a page empty state that carries a description", () => {
    const findings = findViolations(
      page(`<EmptyState
  icon={Boxes}
  title={t("stock.empty.title")}
  description={t("stock.empty.description")}
/>`),
    );
    expect(findings.length).toBe(0);
  });

  it("reads a description written as a multi-line expression", () => {
    const findings = findViolations(
      page(`<EmptyState
  title={t("empty.title")}
  description={
    filters.length > 0
      ? t("empty.filtered")
      : t("empty.description")
  }
/>`),
    );
    expect(findings.length).toBe(0);
  });

  it("does not accept a spread in place of an explicit description", () => {
    const findings = findViolations(
      page(`<EmptyState title={t("empty.title")} {...rest} />`),
    );
    expect(findings.length).toBe(1);
  });

  it("ignores components, tabs and non-page files", () => {
    const findings = findViolations([
      {
        path: "modules/things/components/Panel.tsx",
        text: `<EmptyState title={t("panel.empty")} />`,
      },
      {
        path: "modules/things/pages/tabs/HistoryTab.tsx",
        text: `<EmptyState title={t("history.empty")} />`,
      },
      {
        path: "components/ui/GettingStarted.tsx",
        text: `<EmptyState title={t("start.title")} />`,
      },
    ]);
    expect(findings.length).toBe(0);
  });

  it("follows a page empty state extracted into an *EmptyState helper", () => {
    const helper = `<EmptyState icon={Scale} title={t("empty")} />`;
    for (const path of [
      "modules/recipes/pages/UnitConversionsEmptyState.tsx",
      "modules/inventory/components/items/ItemsEmptyState.tsx",
    ]) {
      const findings = findViolations([{ path, text: helper }]);
      expect(findings.length).toBe(1);
      expect(findings[0]).toContain(path);
    }
  });

  it("passes an *EmptyState helper that carries a description", () => {
    const findings = findViolations([
      {
        path: "modules/inventory/components/items/ItemsEmptyState.tsx",
        text: `<EmptyState title={t("a")} description={t("b")} />`,
      },
    ]);
    expect(findings.length).toBe(0);
  });

  it("ignores a page test file even when it renders the page's empty state", () => {
    const findings = findViolations([
      {
        path: "modules/things/pages/ThingListPage.test.tsx",
        text: `<EmptyState title="x" />`,
      },
    ]);
    expect(findings.length).toBe(0);
  });

  it("does not confuse EmptyStateAction for the empty state itself", () => {
    const findings = findViolations(
      page(`<EmptyStateAction label={t("add")} onClick={open} />`),
    );
    expect(findings.length).toBe(0);
  });
});
