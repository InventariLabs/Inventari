import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { StorageTrackingFields } from "./StorageTrackingFields";
import { tFor } from "@/test/mocks/i18n";

// `t` is a prop, so no provider is needed — but it has to be the real
// translator. An identity stub turns every label assertion into an assertion
// on the key, which holds whether or not the translation exists.
const t = tFor("locations");

describe("StorageTrackingFields", () => {
  it("renders the neutral base fields, not the food-biased legacy set", () => {
    render(<StorageTrackingFields value={[]} onChange={vi.fn()} t={t} />);

    expect(screen.getByText("Product code")).toBeInTheDocument();
    expect(screen.getByText("Price")).toBeInTheDocument();
    expect(
      screen.queryByText("fieldLabels.freeze_date"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("fieldLabels.brand")).not.toBeInTheDocument();
  });

  it("adds a key to `value` when an unchecked field is clicked", () => {
    const onChange = vi.fn();
    render(
      <StorageTrackingFields value={["notes"]} onChange={onChange} t={t} />,
    );

    fireEvent.click(screen.getByText("Price"));

    expect(onChange).toHaveBeenCalledWith(["notes", "price"]);
  });

  it("removes a key when an already-checked field is clicked", () => {
    const onChange = vi.fn();
    render(
      <StorageTrackingFields
        value={["notes", "price"]}
        onChange={onChange}
        t={t}
      />,
    );

    fireEvent.click(screen.getByText("Notes"));

    expect(onChange).toHaveBeenCalledWith(["price"]);
  });

  it("keeps each call site's chrome — `bordered` outlines, `solid` fills", () => {
    const { rerender } = render(
      <StorageTrackingFields value={["notes"]} onChange={vi.fn()} t={t} />,
    );
    const bordered = screen.getByText("Notes").closest("button");
    // One border weight everywhere (§2.10): a selected chip is told apart by
    // colour and fill, not by a heavier frame that shifts its outer box.
    expect(bordered?.className.split(/\s+/)).toContain("border");
    expect(bordered?.className.split(/\s+/)).not.toContain("border-2");
    expect(bordered?.className).toContain("border-primary-400");

    rerender(
      <StorageTrackingFields
        value={["notes"]}
        onChange={vi.fn()}
        t={t}
        variant="solid"
      />,
    );
    const solid = screen.getByText("Notes").closest("button");
    expect(solid?.className.split(/\s+/)).not.toContain("border");
    expect(solid?.className).toContain("justify-start");
  });

  it("sets a selected row's label and check in the brand text token", () => {
    // primary-800 / dark:primary-300 resolve to blue-700 on blue-900 in the
    // Equipment dark palette: 1.5:1. The token follows the profile per theme.
    render(
      <StorageTrackingFields value={["notes"]} onChange={vi.fn()} t={t} />,
    );
    const row = screen.getByText("Notes").closest("button");
    const label = screen.getByText("Notes");
    expect(label).toHaveClass("text-on-primary");
    expect(label.className).not.toMatch(/primary-\d/);
    expect(row?.querySelector("svg.lucide-check")).toHaveClass(
      "text-on-primary",
    );
  });

  it("gives every row the touch floor and a left-aligned label", () => {
    // `size="content"` leaves the height to the content, so a row holding one
    // line of text used to be 21px tall — the padding and the floor have to
    // come from the row itself, in both variants.
    for (const variant of ["bordered", "solid"] as const) {
      const { unmount } = render(
        <StorageTrackingFields
          value={[]}
          onChange={vi.fn()}
          t={t}
          variant={variant}
        />,
      );
      const row = screen.getByText("Notes").closest("button");
      const classes = row?.className.split(/\s+/) ?? [];
      expect(classes).toContain("min-h-11");
      expect(classes).toContain("py-2");
      expect(classes).toContain("text-left");
      unmount();
    }
  });
});
