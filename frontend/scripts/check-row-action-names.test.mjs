import { describe, expect, it } from "vitest";

import {
  rowActionNamesIn,
  rowComponentPaths,
} from "./check-row-action-names.mjs";

/**
 * The gate flags a control repeated per row whose accessible name is the same
 * on every row. Both directions are pinned: names that do not carry the row
 * fire, names that do stay quiet.
 */

const rel = "modules/things/pages/ThingsPage.tsx";

const map = (button) => `const rows = things.map((thing) => (
  <tr key={thing.id}>
    ${button}
  </tr>
));`;

describe("check-row-action-names", () => {
  it("fires on a constant accessible name inside a map", () => {
    expect(rowActionNamesIn(rel, map(`<Button>Revoke</Button>`))).toMatchObject(
      [{ file: rel, label: "Revoke" }],
    );
  });

  it("fires on a constant aria-label inside a map", () => {
    expect(
      rowActionNamesIn(rel, map(`<Button aria-label="Edit connection" />`)),
    ).toMatchObject([{ label: "Edit connection" }]);
  });

  it("leaves a name that interpolates a row property", () => {
    const source = map(
      `<Button aria-label={t("revoke", { name: thing.name })}>Revoke</Button>`,
    );
    expect(rowActionNamesIn(rel, source)).toEqual([]);
  });

  it("reads a row destructured at the parameter", () => {
    const source = `things.map(({ name }) => (
      <Button aria-label={t("revoke", { name })}>Revoke</Button>
    ));`;
    expect(rowActionNamesIn(rel, source)).toEqual([]);
  });

  it("reads a name bound from the row inside the callback", () => {
    const source = `things.map((thing) => {
      const title = thing.name;
      return <Button aria-label={title}>Revoke</Button>;
    });`;
    expect(rowActionNamesIn(rel, source)).toEqual([]);
  });

  it("leaves a control named by another element", () => {
    const source = map(
      `<Button aria-labelledby={\`revoke-\${thing.id}\`}>×</Button>`,
    );
    expect(rowActionNamesIn(rel, source)).toEqual([]);
  });

  it("does not read a nested map with the outer row", () => {
    // The outer row is a day; the inner link names the order, not the day.
    const source = `days.map((day) => (
      <div>
        {day.runs.map((run) => (
          <Link to={run.href}>{run.name}</Link>
        ))}
      </div>
    ));`;
    expect(rowActionNamesIn(rel, source)).toEqual([]);
  });

  it("fires on a condition that chooses between two constant labels", () => {
    const source = map(
      `<Button>{thing.enabled ? t("deactivate") : t("activate")}</Button>`,
    );
    expect(rowActionNamesIn(rel, source)).toMatchObject([
      { label: "deactivate" },
    ]);
  });

  it("reads the card a row is rendered through", () => {
    const page = `import { ThingCard } from "@/modules/things/components/ThingCard";
      things.map((thing) => <ThingCard key={thing.id} thing={thing} />);`;
    const card = `export function ThingCard({ thing }) {
      return <Button>{t("appStore.activate")}</Button>;
    }`;
    const files = [
      { path: rel, text: page },
      { path: "modules/things/components/ThingCard.tsx", text: card },
    ];
    expect([...rowComponentPaths(files)]).toEqual([
      "modules/things/components/ThingCard.tsx",
    ]);
    expect(
      rowActionNamesIn("modules/things/components/ThingCard.tsx", card, {
        whole: true,
      }),
    ).toMatchObject([{ label: "appStore.activate" }]);
  });

  it("leaves a card whose button names the row", () => {
    const card = `export function ThingCard({ thing }) {
      return (
        <Button aria-label={t("remove", { name: thing.name })}>
          {t("remove")}
        </Button>
      );
    }`;
    expect(
      rowActionNamesIn("modules/things/components/ThingCard.tsx", card, {
        whole: true,
      }),
    ).toEqual([]);
  });
});
