import { describe, expect, it } from "vitest";
import {
  classNameAlternatives,
  classNameOf,
  openingTags,
  sizeOf,
  withoutBlockComments,
  withoutComments,
  withoutResponsive,
} from "./lib.mjs";
import buttonSizeOverride from "./button-size-override.mjs";
import contentSizeUnpadded from "./content-size-unpadded.mjs";
import disclosureIndicator from "./disclosure-indicator.mjs";
import footerActionRows from "./footer-action-rows.mjs";
import footerHalfWidth from "./footer-half-width.mjs";
import destructiveOutsideConfirm from "./destructive-outside-confirm.mjs";
import fieldBoxClass from "./field-box-class.mjs";
import labelLineBox from "./label-line-box.mjs";
import overflowRow from "./overflow-row.mjs";

const files = (text) => [{ path: "Fixture.tsx", text }];

describe("openingTags", () => {
  /**
   * The regex this replaced was `<Button\b[^>]*>`, which ends the tag at the
   * arrow of an inline handler. Every button with an `onClick={() => …}` —
   * most of them — reached the detectors without its className, so a gate
   * written to catch `h-auto` never saw the ones that had it.
   */
  it("reads past the arrow of an inline handler", () => {
    const [tag] = openingTags(
      `<Button onClick={() => setOpen(!open)} className="h-auto p-0">`,
      "Button",
    );

    expect(classNameOf(tag.tag)).toBe("h-auto p-0");
  });

  it("reads a className spanning several lines", () => {
    const [tag] = openingTags(
      `<Button\n  variant="ghost"\n  className="w-full h-auto justify-start"\n>`,
      "Button",
    );

    expect(classNameOf(tag.tag)).toBe("w-full h-auto justify-start");
  });

  it("reads a cn() call with calls nested inside it", () => {
    const [tag] = openingTags(
      `<Button className={cn("h-auto", isActive && cn("border", ring()))}>`,
      "Button",
    );

    expect(classNameOf(tag.tag)).toContain("h-auto");
  });

  it("reports no className when the tag sets none", () => {
    const [tag] = openingTags(`<Button onClick={() => save()}>`, "Button");

    expect(classNameOf(tag.tag)).toBeNull();
  });

  /**
   * A prop can hold JSX of its own, and that JSX has classes. Reading the
   * first `className=` in the tag judged a search field by the styling of its
   * clear button.
   */
  it("ignores a className belonging to JSX inside a prop", () => {
    const [tag] = openingTags(
      `<Input rightIcon={<button className="h-11 w-11" />} className="flex-1">`,
      "Input",
    );

    expect(classNameOf(tag.tag)).toBe("flex-1");
  });

  it("reports no className when only a nested element has one", () => {
    const [tag] = openingTags(
      `<Input rightIcon={<button className="h-11 w-11" />} value={v}>`,
      "Input",
    );

    expect(classNameOf(tag.tag)).toBeNull();
  });
});

describe("sizeOf / withoutResponsive", () => {
  it("treats a tag with no size prop as the default size", () => {
    expect(sizeOf(`<Button variant="ghost">`)).toBe("default");
  });

  it("drops the classes that carry a responsive modifier", () => {
    expect(withoutResponsive("h-auto md:h-10 hover:bg-surface")).toBe(
      "h-auto  ",
    );
  });
});

describe("button-size-override", () => {
  it.each([
    ["the default size", `<Button className="h-auto">`],
    ["an explicit size", `<Button size="sm" className="h-9">`],
    ["an icon button", `<Button size="icon" className="w-8">`],
  ])("flags a height class against %s", (_case, source) => {
    expect(buttonSizeOverride.run(files(source)).findings).toHaveLength(1);
  });

  /** Sizes free of responsive modifiers can be overridden safely. */
  it.each([
    ["inline", `<Button size="inline" className="h-auto">`],
    ["iconSm", `<Button size="iconSm" className="h-8 w-8">`],
    ["lg", `<Button size="lg" className="h-14">`],
  ])("leaves size=%s alone", (_size, source) => {
    expect(buttonSizeOverride.run(files(source)).findings).toEqual([]);
  });

  /** `default` pins only the height, so a full-width button is not a finding. */
  it("does not flag a width class on a size that pins no width", () => {
    expect(
      buttonSizeOverride.run(files(`<Button className="w-full">`)).findings,
    ).toEqual([]);
  });

  /**
   * Otherwise the fix has nowhere to go: a call site that answers the
   * variant at its own breakpoint holds at every width, and flagging it
   * would push the author back to the broken form.
   */
  it("accepts a call site that answers the variant at its breakpoint", () => {
    expect(
      buttonSizeOverride.run(files(`<Button className="h-auto md:h-auto">`))
        .findings,
    ).toEqual([]);
  });
});

describe("footer-half-width", () => {
  const dialogFooter = (button) =>
    `<Sheet open>\n  <div className="border-t p-5 flex gap-3">\n    ${button}\n  </div>\n</Sheet>`;

  it("flags a footer button left at `flex-1`", () => {
    expect(
      footerHalfWidth.run(files(dialogFooter(`<Button className="flex-1">`)))
        .findings,
    ).toHaveLength(1);
  });

  it.each([
    ["sm:flex-none", `<Button className="flex-1 sm:flex-none">`],
    ["sm:flex-initial", `<Button className="flex-1 sm:flex-initial">`],
    ["sm:w-auto", `<Button className="flex-1 sm:w-auto">`],
  ])("accepts a footer button released by %s", (_case, button) => {
    expect(footerHalfWidth.run(files(dialogFooter(button))).findings).toEqual(
      [],
    );
  });

  /**
   * A card in a grid is already narrow, so two buttons sharing its width is
   * the right answer. What makes the split wrong is the width being split.
   */
  it("leaves a card's own action row alone", () => {
    const card = `<Card className="p-4">\n  <div className="border-t pt-1 flex gap-2">\n    <Button className="flex-1">\n  </div>\n</Card>`;

    expect(footerHalfWidth.run(files(card)).findings).toEqual([]);
  });

  it("flags a pinned page footer with no dialog around it", () => {
    const page = `<div className="shrink-0 border-t p-4 flex gap-3">\n  <Button className="flex-1">\n</div>`;

    expect(footerHalfWidth.run(files(page)).findings).toHaveLength(1);
  });

  /** The row states the widths, so a call site inside it states none. */
  it("flags a `flex-1` written by hand inside SheetActions", () => {
    const source = `<SheetFooter>\n  <SheetActions>\n    <Button className="flex-1">\n  </SheetActions>\n</SheetFooter>`;

    expect(footerHalfWidth.run(files(source)).findings).toHaveLength(1);
  });
});

describe("overflow-row", () => {
  it("leaves a bar that scrolls its own tabs alone", () => {
    expect(
      overflowRow.run(files(`<TabsList className="w-full">`)).findings,
    ).toEqual([]);
  });

  it("flags an opt-out with nothing else to scroll", () => {
    expect(
      overflowRow.run(files(`<TabsList scrollable={false}>`)).findings,
    ).toHaveLength(1);
  });

  it("accepts an opt-out inside a scroller", () => {
    const source = `<ScrollRow className="flex items-center gap-2">\n  <FilterButton />\n  <Tabs value={tab} onValueChange={setTab} defaultValue={tab}>\n    <TabsList scrollable={false}>`;

    expect(overflowRow.run(files(source)).findings).toEqual([]);
  });

  /**
   * The scroller in `ListControlBar` opens about 400 characters before the
   * list it wraps — a window shorter than that reads correct code as a
   * missing scroller.
   */
  it("sees a scroller several elements above the row", () => {
    const filler = "x".repeat(500);
    const source = `<ScrollRow>\n${filler}\n<TabsList scrollable={false}>`;

    expect(overflowRow.run(files(source)).findings).toEqual([]);
  });
});

describe("destructive-outside-confirm", () => {
  it("flags a filled red button in a row", () => {
    expect(
      destructiveOutsideConfirm.run(files(`<Button variant="destructive">`))
        .findings,
    ).toHaveLength(1);
  });

  /**
   * The first version of this rule searched the file text, so it reported the
   * `variant` prop of anything that takes one — including the confirmation
   * dialog it exists to allow, and a badge nobody can press.
   */
  it.each([
    ["a confirmation dialog", `<ConfirmDialog open variant="danger" />`],
    ["a badge", `<Badge variant="danger">Closed</Badge>`],
  ])("does not read %s as a button", (_case, source) => {
    expect(destructiveOutsideConfirm.run(files(source)).findings).toEqual([]);
  });

  it("accepts a call site that argues for itself", () => {
    const source = `{/* ui-pattern: filled-destructive — this row is the confirmation step itself */}\n<Button variant="danger">`;

    expect(destructiveOutsideConfirm.run(files(source)).findings).toEqual([]);
  });

  /** A marker with no argument behind it is a baseline entry in disguise. */
  it("rejects a marker with no reason worth the name", () => {
    const source = `{/* ui-pattern: filled-destructive — needed */}\n<Button variant="danger">`;

    expect(destructiveOutsideConfirm.run(files(source)).findings).toHaveLength(
      1,
    );
  });
});

describe("field-box-class", () => {
  it.each([
    ["a width", `<Input className="w-24" />`],
    ["a max width", `<Textarea className="max-w-md" />`],
    ["a share of the row", `<NativeSelect className="flex-1" />`],
    ["a margin", `<Select className="mt-1" />`],
    ["a responsive width", `<Input className="xs:w-16" />`],
  ])("flags %s on the control", (_case, source) => {
    expect(fieldBoxClass.run(files(source)).findings).toHaveLength(1);
  });

  it.each([
    ["height", `<Input className="h-8" />`],
    ["type", `<Input className="text-xs text-center" />`],
    ["padding", `<Input className="px-2 py-1.5" />`],
    ["colour", `<Input className="border-amber-200 bg-transparent" />`],
  ])("leaves %s alone — that is the control", (_case, source) => {
    expect(fieldBoxClass.run(files(source)).findings).toEqual([]);
  });

  /** The control is already `w-full`; saying so again is redundant, not wrong. */
  it("does not flag `w-full`", () => {
    expect(
      fieldBoxClass.run(files(`<Input className="w-full" />`)).findings,
    ).toEqual([]);
  });

  it("reads the box prop as the right place for the same class", () => {
    expect(
      fieldBoxClass.run(
        files(`<Input wrapperClassName="w-24" className="h-8" />`),
      ).findings,
    ).toEqual([]);
  });
});

describe("withoutBlockComments", () => {
  it("blanks a comment without moving the code after it", () => {
    const text = `const a = 1;\n/* <label> in prose */\nconst b = 2;`;
    const blanked = withoutBlockComments(text);

    expect(blanked).not.toContain("<label>");
    expect(blanked.split("\n")).toHaveLength(3);
    expect(blanked.split("\n")[2]).toBe("const b = 2;");
  });

  it("keeps the line count of a comment spanning several lines", () => {
    const text = `/**\n * <label className="text-xs">\n */\n<label className="block" />`;

    expect(withoutBlockComments(text).split("\n")).toHaveLength(4);
  });

  /** `//` is in every URL in the corpus; blanking those lines loses code. */
  it("leaves a line comment alone", () => {
    const text = `// see https://example.com/a\nconst a = 1;`;

    expect(withoutBlockComments(text)).toBe(text);
  });
});

describe("label-line-box", () => {
  it("reports a label with no display class", () => {
    expect(
      labelLineBox.run(files(`<label className="text-xs font-medium">`))
        .findings,
    ).toEqual(["Fixture.tsx:1"]);
  });

  it.each([
    ["block", `<label className="block text-xs">`],
    ["a checkbox row", `<label className="flex items-center gap-2">`],
    ["a visually hidden label", `<label className="sr-only">`],
  ])("leaves %s alone", (_case, source) => {
    expect(labelLineBox.run(files(source)).findings).toEqual([]);
  });

  /** Prose about the mistake is not the mistake. */
  it("does not read the examples in a doc comment", () => {
    const source = `/**\n * A hand-rolled <label className="text-xs"> is what this replaces.\n */\nexport const Field = () => null;`;

    expect(labelLineBox.run(files(source)).findings).toEqual([]);
  });

  it("follows `className={fieldLabel}` to the constant beside it", () => {
    const source = `const fieldLabel = "block text-xs uppercase";\n<label className={fieldLabel} htmlFor="name">`;

    expect(labelLineBox.run(files(source)).findings).toEqual([]);
  });

  it("still reports the constant that forgot the display class", () => {
    const source = `const fieldLabel = "text-xs uppercase";\n<label className={fieldLabel} htmlFor="name">`;

    expect(labelLineBox.run(files(source)).findings).toEqual(["Fixture.tsx:2"]);
  });

  it("reports a label with no className at all", () => {
    expect(labelLineBox.run(files(`<label htmlFor="name">`)).findings).toEqual([
      "Fixture.tsx:1",
    ]);
  });

  /**
   * The shared constant is imported, not declared beside the label — judging
   * the caller by a literal it was told not to write reported the files that
   * followed the rule.
   */
  const shared = (classes) => ({
    path: "src/components/ui/fieldLabel.tsx",
    text: `export const FIELD_LABEL_CLASS =\n  "${classes}";`,
  });

  it("follows the imported FIELD_LABEL_CLASS to its own file", () => {
    const caller = {
      path: "Caller.tsx",
      text: `<label className={FIELD_LABEL_CLASS} htmlFor="name">`,
    };

    expect(
      labelLineBox.run([shared("block text-xs uppercase"), caller]).findings,
    ).toEqual([]);
  });

  it("reports every caller if the shared class loses its display token", () => {
    const caller = {
      path: "Caller.tsx",
      text: `<label className={FIELD_LABEL_CLASS} htmlFor="name">`,
    };

    expect(
      labelLineBox.run([shared("text-xs uppercase"), caller]).findings,
    ).toEqual(["Caller.tsx:1"]);
  });
});

describe("withoutComments", () => {
  it("blanks a line comment without moving anything after it", () => {
    const text = `// the old <select> lived here\n<select className="appearance-none">`;
    const clean = withoutComments(text);

    expect(clean).not.toContain("old");
    expect(clean.split("\n")[1]).toBe(`<select className="appearance-none">`);
  });

  it("leaves a URL alone — its `//` is not a comment", () => {
    const text = `const docs = "https://example.com/a";`;

    expect(withoutComments(text)).toBe(text);
  });
});

describe("classNameAlternatives", () => {
  it("returns the expression itself when there is no ternary", () => {
    expect(classNameAlternatives('"w-full px-3"')).toEqual(['"w-full px-3"']);
  });

  /** The shape that rendered a 21px row: only one branch states padding. */
  it("splits a ternary into the class lists it can produce", () => {
    const alternatives = classNameAlternatives(
      'variant === "bordered" ? "px-3 py-2.5 border" : "w-full justify-start"',
    );

    expect(alternatives.some((a) => a.includes("py-2.5"))).toBe(true);
    expect(alternatives.some((a) => !a.includes("py-2.5"))).toBe(true);
  });

  it("does not mistake a responsive prefix inside a string for a ternary", () => {
    expect(classNameAlternatives('"h-11 md:h-10"')).toEqual(['"h-11 md:h-10"']);
  });

  it("keeps the classes that sit outside the ternary in every alternative", () => {
    const alternatives = classNameAlternatives(
      'cn("w-full", checked ? "bg-primary-50" : "bg-surface")',
    );

    expect(alternatives.every((a) => a.includes("w-full"))).toBe(true);
  });
});

describe("content-size-unpadded", () => {
  it("reports a content-sized button that states no vertical rhythm", () => {
    const source = `<Button size="content" className="w-full justify-start">`;

    expect(contentSizeUnpadded.run(files(source)).findings).toEqual([
      "Fixture.tsx:1",
    ]);
  });

  it("reports the bare branch of a ternary whose other half is padded", () => {
    const source = `<Button size="content" className={bordered ? "px-3 py-2.5" : "w-full"}>`;

    expect(contentSizeUnpadded.run(files(source)).findings).toEqual([
      "Fixture.tsx:1",
    ]);
  });

  it("accepts a call site that states the floor itself", () => {
    const source = `<Button size="content" className="py-2 min-h-11 md:min-h-10">`;

    expect(contentSizeUnpadded.run(files(source)).findings).toEqual([]);
  });

  it("says nothing about a size that carries its own height", () => {
    const source = `<Button size="default" className="w-full justify-start">`;

    expect(contentSizeUnpadded.run(files(source)).findings).toEqual([]);
  });
});

describe("footer-action-rows", () => {
  it("reports a footer with two rows of actions", () => {
    const source = `<SheetFooter>\n<SheetActions><Button>Save</Button></SheetActions>\n<SheetActions><Button>Delete</Button></SheetActions>\n</SheetFooter>`;

    expect(footerActionRows.run(files(source)).findings).toEqual([
      "Fixture.tsx:1",
    ]);
  });

  it("reports a destructive action standing in the footer", () => {
    const source = `<SheetFooter>\n<SheetActions>\n<Button variant="ghostDanger">Delete</Button>\n</SheetActions>\n</SheetFooter>`;

    expect(footerActionRows.run(files(source)).findings).toEqual([
      "Fixture.tsx:3",
    ]);
  });

  it("accepts one row of ordinary actions", () => {
    const source = `<SheetFooter>\n<SheetActions>\n<Button variant="outline">Cancel</Button>\n<Button>Save</Button>\n</SheetActions>\n</SheetFooter>`;

    expect(footerActionRows.run(files(source)).findings).toEqual([]);
  });

  it("takes an exception that carries a reason at the call site", () => {
    const source = `<SheetFooter>\n<SheetActions>\n{/* ui-pattern: footer-action — the sheet is itself the confirmation step here */}\n<Button variant="destructive">Delete</Button>\n</SheetActions>\n</SheetFooter>`;

    expect(footerActionRows.run(files(source)).findings).toEqual([]);
  });
});

describe("disclosure-indicator", () => {
  const ui = (text) => [{ path: "components/ui/Fixture.tsx", text }];

  it("reports a <select> that leaves the arrow to the platform", () => {
    const source = `<select className="h-11 md:h-10 px-3">`;

    expect(disclosureIndicator.run(files(source)).findings).toEqual([
      "Fixture.tsx:1",
    ]);
  });

  it("accepts a <select> that draws its own", () => {
    const source = `<select className="h-11 md:h-10 pr-10 appearance-none">`;

    expect(disclosureIndicator.run(files(source)).findings).toEqual([]);
  });

  it("does not read a <select> mentioned in a comment", () => {
    const source = `// the old <select> is gone\nexport const x = 1;`;

    expect(disclosureIndicator.run(files(source)).findings).toEqual([]);
  });

  it("reports a design-system chevron drawn at another size", () => {
    const source = `<button className="h-11 md:h-10">\n<ChevronDown size={20} />\n</button>`;

    expect(disclosureIndicator.run(ui(source)).findings).toEqual([
      "components/ui/Fixture.tsx:2",
    ]);
  });

  it("reports a disclosure control that states no control height", () => {
    const source = `<button className="w-full px-3 py-2.5">\n<ChevronDown size={18} />\n</button>`;

    expect(disclosureIndicator.run(ui(source)).findings).toEqual([
      "components/ui/Fixture.tsx:2",
    ]);
  });

  it("accepts the indicator on a control of the shared height", () => {
    const source = `<button className="min-h-11 md:min-h-10 px-3">\n<ChevronDown size={18} />\n</button>`;

    expect(disclosureIndicator.run(ui(source)).findings).toEqual([]);
  });

  /** A chevron on a card row is a different element — §2.10 does not claim it. */
  it("leaves module chevrons alone", () => {
    const source = `<button className="w-full">\n<ChevronDown size={14} />\n</button>`;

    expect(disclosureIndicator.run(files(source)).findings).toEqual([]);
  });
});
