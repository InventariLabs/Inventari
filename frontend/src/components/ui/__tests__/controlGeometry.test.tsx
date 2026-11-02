import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { buttonVariants } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { Select } from "@/components/ui/Select";
import { DateInput } from "@/components/ui/DateInput";
import { SearchableCombobox } from "@/components/ui/SearchableCombobox";
import { Textarea } from "@/components/ui/Textarea";
import FieldBuilder from "@/components/ui/FieldBuilder";

/**
 * A dialog held two 40px/8px-radius selects with a 44px/12px-radius date field
 * directly below them, and the border weight changed between lists (1px) and
 * dialogs (2px). The scale is documented in UI_GUIDELINES §2.10.
 *
 * Class assertions rather than measurements: jsdom has no layout.
 */

const SCALE = ["h-11", "md:h-10", "rounded-lg"];
const OFF_SCALE = ["border-2", "rounded-xl", "rounded-2xl"];

function expectOnScale(el: HTMLElement) {
  for (const cls of SCALE) expect(el.className.split(/\s+/)).toContain(cls);
  for (const cls of OFF_SCALE)
    expect(el.className.split(/\s+/)).not.toContain(cls);
}

describe("form controls share one geometry scale", () => {
  it("Input", () => {
    render(<Input aria-label="Name" />);
    expectOnScale(screen.getByRole("textbox"));
  });

  it("NativeSelect", () => {
    render(
      <NativeSelect aria-label="Unit">
        <option value="pcs">pcs</option>
      </NativeSelect>,
    );
    expectOnScale(screen.getByRole("combobox"));
  });

  it("Select", () => {
    render(
      <Select
        options={[{ id: "1", name: "Cold Storage" }]}
        value=""
        onChange={vi.fn()}
        label="Partner"
      />,
    );
    expectOnScale(screen.getByRole("combobox"));
  });

  it("DateInput", () => {
    render(
      <DateInput value="" onChange={vi.fn()} aria-label="Scheduled date" />,
    );
    expectOnScale(screen.getByRole("combobox", { name: "Scheduled date" }));
  });

  it("SearchableCombobox", () => {
    render(
      <SearchableCombobox
        options={[{ id: "1", name: "Cold Storage" }]}
        value=""
        onChange={vi.fn()}
        label="All storages"
        title="All storages"
      />,
    );
    expectOnScale(screen.getByRole("combobox", { name: "All storages" }));
  });
});

/**
 * `SearchableCombobox` carried `outline-none` and no ring, so keyboard focus
 * was invisible on it. Nobody noticed while a filled trigger still painted its
 * border green; once "filled is not a state" landed (§2.10) there was nothing
 * left to see. A geometry scale that every control joins needs a focus scale
 * every control joins too.
 */
describe("every form control shows where the keyboard is", () => {
  const hasRing = (el: HTMLElement) =>
    el.className
      .split(/\s+/)
      .some((c) => c === "focus:ring-2" || c === "focus-visible:ring-2");

  it("Input", () => {
    render(<Input aria-label="Name" />);
    expect(hasRing(screen.getByRole("textbox"))).toBe(true);
  });

  it("Textarea", () => {
    render(<Textarea aria-label="Notes" />);
    expect(hasRing(screen.getByRole("textbox"))).toBe(true);
  });

  it("NativeSelect", () => {
    render(
      <NativeSelect aria-label="Unit">
        <option value="pcs">pcs</option>
      </NativeSelect>,
    );
    expect(hasRing(screen.getByRole("combobox"))).toBe(true);
  });

  it("Select", () => {
    render(
      <Select
        options={[{ id: "1", name: "Cold Storage" }]}
        value=""
        onChange={vi.fn()}
        label="Partner"
      />,
    );
    expect(hasRing(screen.getByRole("combobox"))).toBe(true);
  });

  it("SearchableCombobox", () => {
    render(
      <SearchableCombobox
        options={[{ id: "1", name: "Cold Storage" }]}
        value=""
        onChange={vi.fn()}
        label="All storages"
        title="All storages"
      />,
    );
    expect(
      hasRing(screen.getByRole("combobox", { name: "All storages" })),
    ).toBe(true);
  });
});

/**
 * `icon` was the one size with no `gap`, which is invisible until a call site
 * widens the button to show its label beside the glyph — the partner rows did
 * (`md:w-auto md:px-3`) and shipped "✏Edit" with the two touching.
 */
describe("a button spaces its icon from its label", () => {
  // Every size but `inline`, which is a single glyph inside a line of content
  // and has nothing to space.
  const SIZES = [
    "default",
    "sm",
    "md",
    "lg",
    "icon",
    "iconSm",
    "row",
    "content",
    "contentSm",
  ] as const;

  it.each(SIZES)("size=%s", (size) => {
    const classes = buttonVariants({ size }).split(/\s+/);
    expect(classes.some((c) => /^gap-/.test(c))).toBe(true);
  });
});

describe("disclosure cards that read as dropdowns keep the same frame", () => {
  it("FieldBuilder collapsed card", () => {
    render(<FieldBuilder fields={[]} onChange={vi.fn()} />);
    const toggle = screen.getByRole("button");
    const card = toggle.parentElement as HTMLElement;
    // The chevron makes the collapsed card read as a dropdown — next to the
    // 40px/8px/1px selects in the same dialog a 66px card with a 2px/12px
    // frame sticks out (UI_GUIDELINES §2.10).
    for (const cls of ["border", "rounded-lg"])
      expect(card.className.split(/\s+/)).toContain(cls);
    for (const cls of OFF_SCALE)
      expect(card.className.split(/\s+/)).not.toContain(cls);
    // Two content lines keep it taller than h-10, but the padding joins the
    // scale's px-3 instead of a roomier p-4.
    expect(toggle.className.split(/\s+/)).toContain("px-3");
    expect(toggle.className.split(/\s+/)).not.toContain("p-4");
  });
});

describe("labelled controls own the label-to-field gap", () => {
  it.each([
    ["Input", <Input key="input" label="Partner" />],
    [
      "NativeSelect",
      <NativeSelect key="native" label="Partner">
        <option value="a">a</option>
      </NativeSelect>,
    ],
    [
      "Select",
      <Select
        key="select"
        options={[{ id: "1", name: "Acme" }]}
        value=""
        onChange={vi.fn()}
        label="Partner"
      />,
    ],
    [
      "DateInput",
      <DateInput key="date" value="" onChange={vi.fn()} label="Partner" />,
    ],
    ["Textarea", <Textarea key="textarea" label="Partner" />],
  ])("%s wraps its label in the shared 6px stack", (_name, element) => {
    const { container } = render(element);
    const label = screen.getByText("Partner");
    expect(label.tagName).toBe("LABEL");
    // The label must point at the control, and the wrapper must be the element
    // that spaces them — a caller adding its own <label> reintroduces the 0px gap.
    expect(label.getAttribute("for")).toBeTruthy();
    expect(container.querySelector(".space-y-1\\.5")).not.toBeNull();
    // …and it must be a block. An inline label sits in a line box sized by the
    // wrapper's inherited line-height, which dropped the field ~8px below the
    // block-labelled control next to it in the same grid row.
    expect(label.className.split(/\s+/)).toContain("block");
  });
  it("FieldBuilder header does not outweigh the labels around it", () => {
    render(<FieldBuilder fields={[]} onChange={vi.fn()} />);
    const toggle = screen.getByRole("button");
    // §1.2: form captions are `font-medium`. A bold title over the modal's
    // only bold-free column made the collapsed section the heaviest element
    // in it, on top of the extra height and the thicker frame.
    expect(toggle.className).not.toContain("font-bold");
    expect(toggle.querySelector(".font-bold")).toBeNull();
  });

  it("FieldBuilder shows a subtitle only when it says something new", () => {
    const { rerender } = render(
      <FieldBuilder fields={[]} onChange={vi.fn()} />,
    );
    const toggle = screen.getByRole("button");
    // Empty: the section label above it and the title already name the thing.
    expect(toggle.querySelectorAll("p")).toHaveLength(0);

    rerender(
      <FieldBuilder
        fields={[
          {
            key: "size",
            label: "Size",
            type: "text",
            visible: true,
            required: false,
            is_system: false,
          },
        ]}
        onChange={vi.fn()}
      />,
    );
    // With fields, the count is information the title does not carry.
    expect(screen.getByRole("button").querySelectorAll("p")).toHaveLength(1);
  });
});
