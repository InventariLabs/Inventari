import { describe, expect, it } from "vitest";
import iconButtonUnnamed from "./icon-button-unnamed.mjs";

const file = (text) => [{ path: "modules/things/ThingRow.tsx", text }];

describe("icon-button-unnamed", () => {
  it("claims a button whose only content is an icon, whatever size it declares", () => {
    // The size test alone missed eight of these on one screen: `size="sm"`
    // with a single lock inside is exactly as unannounced as `size="icon"`.
    const { findings } = iconButtonUnnamed.run(
      file(`<Button size="sm" variant="outline" onClick={close}>
  <Lock size={14} />
</Button>`),
    );

    expect(findings).toEqual(["modules/things/ThingRow.tsx:1"]);
  });

  it("still claims a declared icon size", () => {
    const { findings } = iconButtonUnnamed.run(
      file(`<Button size="iconSm" onClick={x}>{spinner}</Button>`),
    );

    expect(findings).toEqual(["modules/things/ThingRow.tsx:1"]);
  });

  it("leaves a button that has a name", () => {
    const { findings } = iconButtonUnnamed.run(
      file(`<Button size="sm" aria-label={t("a11y.delete")}>
  <Trash2 size={14} />
</Button>`),
    );

    expect(findings).toEqual([]);
  });

  it("leaves a button whose text sits in a span beside the icon", () => {
    // The first run of the content half claimed the language switcher: a lazy
    // regex for "an element" swallowed the span up to the icon's own `/>`,
    // and the visible words went with it.
    const { findings } = iconButtonUnnamed.run(
      file(`<Button variant="ghost" size="contentSm">
  <span className="text-xs">{currentLanguage.name}</span>
  <ChevronDown size={14} className={\`\${isOpen ? "rotate-180" : ""}\`} />
</Button>`),
    );

    expect(findings).toEqual([]);
  });

  it("leaves a button whose label is an expression it cannot evaluate", () => {
    // Claiming only what it is sure of: `{label}` may well be a word.
    const { findings } = iconButtonUnnamed.run(
      file(`<Button variant="ghost">{label}</Button>`),
    );

    expect(findings).toEqual([]);
  });

  it("reads its own children when one button wraps another", () => {
    const { findings } = iconButtonUnnamed.run(
      file(`<Button variant="ghost">
  <Button size="iconSm" aria-label={t("a11y.close")}>
    <X size={14} />
  </Button>
  {t("actions.save")}
</Button>`),
    );

    expect(findings).toEqual([]);
  });

  it("is not fooled by a `>` inside an attribute", () => {
    const { findings } = iconButtonUnnamed.run(
      file(`<Button variant="ghost" onClick={() => remove(id)}>
  <X size={14} />
</Button>`),
    );

    expect(findings).toEqual(["modules/things/ThingRow.tsx:1"]);
  });

  it("does not count a commented-out button", () => {
    const { considered } = iconButtonUnnamed.run(
      file(`// <Button size="icon"><X /></Button>
const x = 1;`),
    );

    expect(considered).toBe(0);
  });
});
