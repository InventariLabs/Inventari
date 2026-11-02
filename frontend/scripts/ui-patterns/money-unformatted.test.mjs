import { describe, expect, it } from "vitest";
import moneyUnformatted from "./money-unformatted.mjs";

const file = (text, path = "modules/things/ThingPage.tsx") => [{ path, text }];

describe("money-unformatted", () => {
  it("flags an amount interpolated straight into JSX text", () => {
    const { considered, findings } = moneyUnformatted.run(
      file(`export const A = () => (
  <div>
    <span>{breakdown.total_cost}</span>
  </div>
);`),
    );

    expect(considered).toBe(1);
    expect(findings).toEqual(["modules/things/ThingPage.tsx:3"]);
  });

  it("flags each raw amount on its own line, sorted", () => {
    const { findings } = moneyUnformatted.run(
      file(`<p>
  <b>{row.unit_price}</b>
  <i>{row.amount}</i>
</p>`),
    );

    expect(findings).toEqual([
      "modules/things/ThingPage.tsx:2",
      "modules/things/ThingPage.tsx:3",
    ]);
  });

  it("accepts amounts wrapped in money(), formatMoney() or t()", () => {
    const { findings } = moneyUnformatted.run(
      file(`<div>
  <span>{money(breakdown.total_cost)}</span>
  <span>{formatMoney(row.price, "PLN", "pl")}</span>
  <span>{t("cost", { value: row.cost })}</span>
</div>`),
    );

    expect(findings).toEqual([]);
  });

  it("does not report a label that merely shares the field's name", () => {
    const { findings } = moneyUnformatted.run(
      file(`<th>{labels.subtotal}</th>
<th>{texts.price}</th>`),
    );

    expect(findings).toEqual([]);
  });

  it("does not report an amount outside text position (attribute, object literal)", () => {
    const { findings } = moneyUnformatted.run(
      file(`const body = { cost: row.cost, price: row.price };
const el = <input value={row.unit_price} />;`),
    );

    expect(findings).toEqual([]);
  });

  it("ignores amounts that only appear in comments", () => {
    const { findings } = moneyUnformatted.run(
      file(`<div>
  {/* {row.total_cost} */}
  {
    // row.price
  }
</div>`),
    );

    expect(findings).toEqual([]);
  });

  it("walks into a wrapping block and reports the leaf", () => {
    const { findings } = moneyUnformatted.run(
      file(`<div>
  {rows.length > 0 && (
    <span>{row.sale_price}</span>
  )}
</div>`),
    );

    expect(findings).toEqual(["modules/things/ThingPage.tsx:3"]);
  });

  it("does not consider files without a money field", () => {
    const { considered, findings } = moneyUnformatted.run(
      file(`<span>{item.quantity}</span>`),
    );

    expect(considered).toBe(0);
    expect(findings).toEqual([]);
  });
});
