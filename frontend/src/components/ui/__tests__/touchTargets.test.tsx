import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { render as renderWithProviders } from "@/test/utils";
import { ListControlBar } from "@/components/ui/ListControlBar";
import { SearchableCombobox } from "@/components/ui/SearchableCombobox";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/Dialog";
import { Sheet, SheetBody, SheetHeader } from "@/components/ui/Sheet";
import { DateInput } from "@/components/ui/DateInput";
import { CompositionRow } from "@/components/ui/CompositionBar";

/**
 * A layout check measured the list in its
 * default state and found nothing under 44px, but controls that only appear
 * once a filter or a search is active were never in frame.
 *
 * These assert the class rather than the rendered box because jsdom has no
 * layout; the live measurement lives in `tests/e2e/audit-responsive.spec.ts`.
 */
describe("controls that appear only when filtering", () => {
  it("gives the clear-search button a mobile touch target", () => {
    render(
      <ListControlBar
        search={{ value: "milk", onChange: vi.fn(), placeholder: "Search..." }}
      />,
    );

    // Measured at 15x15 before the fix — the bare icon, with no box of its own.
    const clear = screen.getByRole("button", { name: /clear/i });
    expect(clear.className).toContain("h-11");
    expect(clear.className).toContain("w-11");
    expect(clear.className).toContain("md:h-auto");
  });

  it("gives the combobox trigger a mobile touch target", () => {
    render(
      <SearchableCombobox
        options={[{ id: "1", name: "Cold Storage" }]}
        value=""
        onChange={vi.fn()}
        label="All storages"
        title="All storages"
      />,
    );

    // Measured at 40px — the filter pickers on the product list.
    const trigger = screen.getByRole("combobox", { name: "All storages" });
    expect(trigger.className).toContain("h-11");
    expect(trigger.className).toContain("md:h-10");
  });
});

/**
 * One rule for the controls a 390px phone puts under a thumb — a control
 * is at least 44px in its shorter dimension, the
 * floor `Button size="icon"` already gives (`h-11 md:h-10`), and the height
 * a link in a row is given by padding. jsdom lays nothing out, so the class
 * is what is asserted here; the real sizes were measured with
 * `getBoundingClientRect` on 390x844 and 320x568 screens.
 */
describe("the dialog and the sheet close with the same target", () => {
  it("gives the dialog's own close button a 44px box below md", () => {
    renderWithProviders(
      <Dialog open>
        <DialogContent aria-label="Checkout">
          <DialogTitle>Checkout</DialogTitle>
        </DialogContent>
      </Dialog>,
    );

    // 16x16: the glyph and nothing around it (Dialog.tsx).
    const close = screen.getByRole("button", { name: "Close" });
    expect(close.className).toContain("h-11");
    expect(close.className).toContain("w-11");
    expect(close.className).toContain("md:h-10");
  });

  it("gives the sheet's close button the same box", () => {
    renderWithProviders(
      <Sheet open onClose={vi.fn()} aria-label="Storage">
        <SheetHeader title="Storage" onClose={vi.fn()} />
        <SheetBody>Shelf A</SheetBody>
      </Sheet>,
    );

    const close = screen.getByRole("button", { name: "Close" });
    expect(close.className).toContain("h-11");
    expect(close.className).toContain("w-11");
    expect(close.className).toContain("md:h-10");
  });
});

describe("the date sheet below md has a way out", () => {
  it("shows a header that names it and closes it, leaving the date alone", () => {
    const onChange = vi.fn();
    renderWithProviders(
      <DateInput
        value="2026-09-08"
        onChange={onChange}
        aria-label="Due date"
      />,
    );

    // The sheet was `<SheetBody>` alone: no heading, no ×, nothing on it
    // said who opened it or how to leave — Escape and a background tap
    // worked, and neither was visible.
    fireEvent.click(screen.getByRole("combobox", { name: "Due date" }));
    expect(
      screen.getByRole("heading", { name: "Choose a date" }),
    ).toBeInTheDocument();

    const close = screen.getByRole("button", { name: "Close" });
    expect(close.className).toContain("h-11");
    fireEvent.click(close);

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("links in rows reach the 44px floor", () => {
  it("gives a composition row's name link the floor", () => {
    renderWithProviders(
      <ul>
        <CompositionRow
          icon="Package"
          name="Laptops"
          href="/equipment/assets?category=c1"
          count={18}
          maxCount={18}
          segments={[
            { key: "issued", count: 11, tone: "active" },
            { key: "ok", count: 7, tone: "ok" },
          ]}
          ariaLabel="18 assets: 11 issued"
        />
      </ul>,
    );

    const link = screen.getByRole("link", { name: "Laptops" });
    // 244x20 as measured: text-sm sits on a 20px line, so 12px of padding a
    // side is the 44px, and the desktop row gives back what it can.
    expect(link.className).toContain("py-3");
    expect(link.className).toContain("md:py-1");
  });
});
