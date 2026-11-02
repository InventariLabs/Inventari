/**
 * Four of these are the measurements that changed the scanner: the three
 * false positives it used to report (a column name in an import mapping, a
 * payload key, a decision in a statement) and the false NEGATIVE that a
 * character window let through — a raw render one line under a resolved one.
 */
import { describe, expect, it } from "vitest";

import {
  diffBaseline,
  enclosingCalls,
  isPayloadObject,
  isScanned,
  isStatement,
  localResolvers,
  rawUnitsIn,
} from "./check-quantity-render.mjs";

describe("rawUnitsIn", () => {
  it("reports a bare render", () => {
    expect(rawUnitsIn("a.tsx", '<span>{line.uom_symbol ?? ""}</span>')).toEqual(
      [{ file: "a.tsx", line: 1 }],
    );
  });

  it("reports a symbol interpolated into a translated sentence", () => {
    // This is how "pcs" gets inside a Polish sentence: the sentence is
    // translated, the symbol is not.
    const text = '{t("form.price_per", { unit: ing.uom_symbol })}';
    expect(rawUnitsIn("a.tsx", text)).toHaveLength(1);
  });

  it("accepts a symbol handed to a shared resolver", () => {
    const text = "{formatQuantityLocalized(t, s.needed, s.uom_symbol)}";
    expect(rawUnitsIn("a.tsx", text)).toEqual([]);
  });

  it("accepts a symbol handed to the documents resolver", () => {
    expect(
      rawUnitsIn("a.tsx", "{getDocumentUnitLabel(t, ln.uom_symbol)}"),
    ).toEqual([]);
  });

  it("accepts a symbol handed to the WMS empty-unit resolver", () => {
    // `wmsUnitLabel` is `unitLabel` with one answer for the empty unit: the
    // symbol still goes through `common:units.`, so the screen never prints
    // the wire's own spelling.
    expect(rawUnitsIn("a.tsx", "{wmsUnitLabel(t, line.uom_symbol)}")).toEqual(
      [],
    );
  });

  it("accepts a catalogue lookup whose fallback is the symbol", () => {
    const text =
      "{tDyn(`common:units.${item.uom.symbol}`, { defaultValue: item.uom.symbol })}";
    expect(rawUnitsIn("a.tsx", text)).toEqual([]);
  });

  it("accepts the second unit catalogue, keyed by name", () => {
    const text =
      "{t(`items:uomSymbols.${uom.name}`, { defaultValue: uom.symbol })}";
    expect(rawUnitsIn("a.tsx", text)).toEqual([]);
  });

  it("reports a raw render on the line under a resolved one", () => {
    // The measurement that removed the character window: a planted
    // `<span>{s.uom_symbol}</span>` under a resolved call went straight
    // through, because the resolver was 40 characters away. Proximity is not
    // evidence; enclosure is.
    const text = [
      "{formatQuantityLocalized(t, s.needed, s.uom_symbol)}",
      "<span>{s.uom_symbol}</span>",
    ].join("\n");
    expect(rawUnitsIn("a.tsx", text)).toEqual([{ file: "a.tsx", line: 2 }]);
  });

  it("accepts a local wrapper whose body reaches a resolver", () => {
    const text = [
      "const quantity = (v, symbol) => formatQuantityLocalized(t, v, symbol);",
      "<td>{quantity(row.quantity, row.uom_symbol)}</td>",
    ].join("\n");
    expect(rawUnitsIn("a.tsx", text)).toEqual([]);
  });

  it("reports a local wrapper that only appends the symbol", () => {
    const text = [
      "const unitSuffix = (uom) => <span>{uom}</span>;",
      "<td>{unitSuffix(line.uom_symbol)}</td>",
    ].join("\n");
    expect(rawUnitsIn("a.tsx", text)).toHaveLength(1);
  });

  it("ignores a column name written as a string", () => {
    const text = '{ key: "uom_symbol", label: t("import.uom") }';
    expect(rawUnitsIn("a.tsx", text)).toEqual([]);
  });

  it("ignores the symbol used as an object key", () => {
    expect(
      rawUnitsIn("a.tsx", "{ uom_symbol: tpl.unit, name: tpl.name }"),
    ).toEqual([]);
  });

  it("ignores a decision taken in a statement", () => {
    const text = "{ const ok = COUNTABLE.has(i.uom_symbol); return ok; }";
    expect(rawUnitsIn("a.tsx", text)).toEqual([]);
  });

  it("reports a symbol kept in a variable and rendered into JSX", () => {
    // The read sits in a statement — the binding — and the render shows a
    // name the scanner never followed: `const unit = …uom_symbol` on the
    // counting card, `{unit}` in the figures beside it.
    const text = [
      "function C() {",
      "  const unit = line.uom_symbol?.trim() || null;",
      "  return <span>{unit}</span>;",
      "}",
    ].join("\n");
    expect(rawUnitsIn("a.tsx", text)).toEqual([{ file: "a.tsx", line: 3 }]);
  });

  it("reports a symbol kept in a variable and interpolated into a sentence", () => {
    // The step buttons' shape: the sentence goes through `t`, the symbol
    // inside it does not.
    const text = [
      "function C() {",
      "  const unit = stockTakeItem.uom_symbol;",
      '  return t("item.decreaseCountInUnit", { unit, name });',
      "}",
    ].join("\n");
    expect(rawUnitsIn("a.tsx", text)).toEqual([{ file: "a.tsx", line: 3 }]);
  });

  it("accepts a symbol kept in a variable and handed to a resolver", () => {
    const text = [
      "function C() {",
      "  const unit = line.uom_symbol?.trim() || null;",
      "  return <span>{formatQuantityLocalized(t, value, unit)}</span>;",
      "}",
    ].join("\n");
    expect(rawUnitsIn("a.tsx", text)).toEqual([]);
  });

  it("accepts a symbol kept in a variable and bound through a resolver", () => {
    const text = [
      "function C() {",
      "  const unit = unitLabel(t, line.uom_symbol);",
      "  return <span>{unit}</span>;",
      "}",
    ].join("\n");
    expect(rawUnitsIn("a.tsx", text)).toEqual([]);
  });

  it("lets a bound symbol handed to a component prop through", () => {
    // `uomSymbol={uomSymbol}` gives the raw symbol to a component that asked
    // for it — precision, a step — not to a sentence. Whether it is printed
    // is the consumer's render, read where the consumer writes it.
    const text = [
      "function C() {",
      "  const uomSymbol = line.uom_symbol ?? null;",
      "  return <QuantityInput uomSymbol={uomSymbol} />;",
      "}",
    ].join("\n");
    expect(rawUnitsIn("a.tsx", text)).toEqual([]);
  });

  it("lets a symbol read straight into a component prop through", () => {
    // The same hand-over without a name in between: `uomSymbol={item.uom_symbol}`
    // is a value given to a consumer, not a sentence.
    const text = '<QuantityInput uomSymbol={item.uom_symbol} />';
    expect(rawUnitsIn("a.tsx", text)).toEqual([]);
  });

  it("still reports a symbol printed as text or interpolated beside a prop", () => {
    // The prop exclusion is the attribute's own braces and nothing wider:
    // a render in the element body, a template literal inside an attribute
    // and a translator argument keep their red.
    expect(
      rawUnitsIn("a.tsx", "<span>{item.uom_symbol}</span>"),
    ).toHaveLength(1);
    expect(
      rawUnitsIn("a.tsx", "<span title={`${item.uom_symbol} each`} />"),
    ).toHaveLength(1);
    expect(
      rawUnitsIn(
        "a.tsx",
        '<Hint label={t("k", { unit: item.uom_symbol })} />',
      ),
    ).toHaveLength(1);
  });

  it("does not follow a predicate computed from the symbol", () => {
    // `className={isCountable}` is not a sentence about units: the name holds
    // the boolean the predicate answered, not the symbol.
    const text = [
      "function C() {",
      "  const isCountable = COUNTABLE.has(item.uom_symbol);",
      '  return <span className={isCountable ? "a" : "b"}>x</span>;',
      "}",
    ].join("\n");
    expect(rawUnitsIn("a.tsx", text)).toEqual([]);
  });

  it("does not follow a handler built around the symbol", () => {
    const text = [
      "function C() {",
      "  const show = useCallback(() => toast(line.uom_symbol), []);",
      "  return <button onClick={show}>x</button>;",
      "}",
    ].join("\n");
    expect(rawUnitsIn("a.tsx", text)).toEqual([]);
  });

  it("follows a binding inside the wrapper the RHS is passed to", () => {
    // The `memo(` call is open across the read, but it is not what the
    // right-hand side computed: the binding still carries the symbol out.
    const text = [
      "const C = memo(function C() {",
      "  const unit = line.uom_symbol ?? null;",
      "  return <span>{unit}</span>;",
      "});",
    ].join("\n");
    expect(rawUnitsIn("a.tsx", text)).toEqual([{ file: "a.tsx", line: 3 }]);
  });

  it("ignores a read inside a comment", () => {
    expect(
      rawUnitsIn("a.tsx", "// {line.uom_symbol} used to print here\n"),
    ).toEqual([]);
  });
});

describe("enclosingCalls", () => {
  it("names the call whose parentheses are still open", () => {
    const text = "wrap(a, b.uom_symbol)";
    const at = text.indexOf("uom_symbol");
    expect(enclosingCalls(text, at).map((c) => c.name)).toContain("wrap");
  });

  it("does not name a call that has already closed", () => {
    const text = "done(x) + b.uom_symbol";
    const at = text.indexOf("uom_symbol");
    expect(enclosingCalls(text, at).map((c) => c.name)).not.toContain("done");
  });
});

describe("localResolvers", () => {
  it("collects a wrapper around a shared resolver", () => {
    const text = "const q = (v) => formatQuantityLocalized(t, v, null);";
    expect([...localResolvers(text)]).toContain("q");
  });

  it("leaves out a wrapper that resolves nothing", () => {
    expect([...localResolvers("const s = (u) => u ?? '';")]).not.toContain("s");
  });
});

describe("isStatement", () => {
  it("reads a semicolon as a statement", () => {
    expect(isStatement("{ const a = 1; }")).toBe(true);
  });

  it("does not read a plain expression as one", () => {
    expect(isStatement("{line.uom_symbol}")).toBe(false);
  });
});

describe("isScanned", () => {
  it("leaves the resolvers' own files alone", () => {
    expect(isScanned("lib/i18nHelpers.ts")).toBe(false);
    expect(isScanned("utils/formatters.ts")).toBe(false);
    expect(isScanned("modules/warehouse/unitLabels.ts")).toBe(false);
    expect(isScanned("modules/x/components/Y.tsx")).toBe(true);
  });
});

describe("diffBaseline", () => {
  it("fails a second raw read in a file the baseline holds", () => {
    const { added } = diffBaseline(
      [
        { file: "a.tsx", line: 1 },
        { file: "a.tsx", line: 4 },
      ],
      { "a.tsx": 1 },
    );
    expect(added).toEqual([{ key: "a.tsx", was: 1, now: 2 }]);
  });
});

describe("isPayloadObject", () => {
  it("lets an object built for a form through", () => {
    expect(
      isPayloadObject("{ uom_id: rule.uom_id, uom_symbol: rule.uom_symbol }"),
    ).toBe(true);
  });

  it("keeps the interpolation object of a sentence", () => {
    // `t("picking.short_pick_description", { uom: line.uom_symbol })` is how
    // "pcs" gets inside a translated sentence — the one object that renders.
    expect(
      isPayloadObject("{ uom: line.uom_symbol }", [{ name: "t", args: "" }]),
    ).toBe(false);
  });

  it("is not fooled by a JSX expression that only looks like an object", () => {
    expect(isPayloadObject("{line.uom_symbol}")).toBe(false);
  });
});
