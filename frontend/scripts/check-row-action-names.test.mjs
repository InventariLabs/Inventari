import { describe, expect, it } from "vitest";

import {
  rowActionNamesIn,
  rowComponentPaths,
  withKeys,
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

  it("reads the card a row is rendered through a relative import", () => {
    const page = `import { ThingCard } from "./ThingCard";
      things.map((thing) => <ThingCard key={thing.id} thing={thing} />);`;
    const files = [
      { path: "modules/things/components/ThingsBoard.tsx", text: page },
      {
        path: "modules/things/components/ThingCard.tsx",
        text: `export function ThingCard({ thing }) {
          return <Button>Activate</Button>;
        }`,
      },
    ];
    expect([...rowComponentPaths(files)]).toEqual([
      "modules/things/components/ThingCard.tsx",
    ]);
  });

  it("reports two rows with the same constant name as two sites", () => {
    const source = `things.map((thing) => (
      <div>
        <Button>Edit</Button>
        <Button>Edit</Button>
      </div>
    ));`;
    const findings = rowActionNamesIn(rel, source);
    expect(findings).toHaveLength(2);
    expect(new Set(withKeys(findings).map((finding) => finding.key)).size).toBe(
      2,
    );
  });

  it("reads an aria-label inside a card rendered per row", () => {
    // The AI connection card: the button's name is its aria-label, and the
    // card's own file holds no map.
    const card = `export function ThingCard({ thing }) {
      return <Button aria-label={t("config.editConnection")} />;
    }`;
    expect(
      rowActionNamesIn("modules/things/components/ThingCard.tsx", card, {
        whole: true,
      }),
    ).toMatchObject([{ label: "config.editConnection" }]);
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

  it("reads the label of an ActionMenu inside a map", () => {
    // `ActionMenu` carries its trigger's accessible name in `label`, and no
    // Button, anchor or `onClick` appears in the row's own markup.
    expect(
      rowActionNamesIn(
        rel,
        map(`<ActionMenu actions={menu} label={t("moreActions")} />`),
      ),
    ).toMatchObject([{ label: "moreActions" }]);
  });

  it("leaves an ActionMenu whose label names the row", () => {
    const source = map(
      `<ActionMenu actions={menu} label={t("moreFor", { name: thing.name })} />`,
    );
    expect(rowActionNamesIn(rel, source)).toEqual([]);
  });

  it("reads an ActionMenu in a card rendered per row", () => {
    const card = `export function ThingCard({ thing }) {
      return <ActionMenu actions={menu} label={t("moreActions")} />;
    }`;
    expect(
      rowActionNamesIn("modules/things/components/ThingCard.tsx", card, {
        whole: true,
      }),
    ).toMatchObject([{ label: "moreActions" }]);
  });
});
