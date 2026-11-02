import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/test/utils";
import { BulkActionBar } from "./BulkActionBar";

const words: Record<string, string> = {
  "bulk.printNone": "Print as one PDF",
  "bulk.printNoneReason": "Nothing to print: only drafts are selected",
};

const t = (key: string, options?: Record<string, unknown>) =>
  words[key.replace("warehouse:", "")] ??
  (options?.count !== undefined
    ? `${key.replace("warehouse:", "")}:${options.count}`
    : key.replace("warehouse:", ""));

function renderBar(
  overrides: Partial<React.ComponentProps<typeof BulkActionBar>> = {},
) {
  return render(
    <BulkActionBar
      selectedCount={3}
      draftCount={2}
      printableCount={1}
      pickableIds={[]}
      isDeleting={false}
      isConfirming={false}
      isPrinting={false}
      onConfirmDrafts={vi.fn()}
      onPrint={vi.fn()}
      onDeleteDrafts={vi.fn()}
      onExportCsv={vi.fn()}
      onClear={vi.fn()}
      onPick={vi.fn()}
      t={t}
      {...overrides}
    />,
  );
}

describe("BulkActionBar", () => {
  it("offers every action by name", () => {
    renderBar();
    for (const name of [
      "bulk.exportCsv",
      "bulk.print:1",
      "bulk.confirmDrafts:2",
      "bulk.deleteDrafts:2",
      "bulk.clear",
    ]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
  });

  it("never reads 'Print 0' when only drafts are ticked", () => {
    renderBar({ printableCount: 0 });
    const print = screen.getByRole("button", { name: "Print as one PDF" });
    expect(print).toBeDisabled();
    expect(print.parentElement).toHaveAttribute(
      "title",
      "Nothing to print: only drafts are selected",
    );
    expect(screen.queryByText("bulk.print:0")).not.toBeInTheDocument();
  });

  it("starts a pick session over the ticked dispatches, in list order", () => {
    const onPick = vi.fn();
    renderBar({ pickableIds: ["b", "a"], onPick });
    fireEvent.click(
      screen.getByRole("button", { name: "bulk.pickSelected:2" }),
    );
    expect(onPick).toHaveBeenCalledWith(["b", "a"]);
  });

  it("offers no pick action when no confirmed dispatch is ticked", () => {
    renderBar();
    expect(
      screen.queryByRole("button", { name: /pickSelected/ }),
    ).not.toBeInTheDocument();
  });

  it("wraps onto a second row instead of overflowing a phone", () => {
    // jsdom has no layout to measure, so what can be checked is that neither
    // the bar nor its button group is a no-wrap row: with five actions the
    // buttons would otherwise run past a 375px screen.
    renderBar();
    const bar = screen.getByText("bulk.selectedCount:3").closest(".sticky");
    expect(bar).toHaveClass("flex-wrap");
    const group = screen
      .getByRole("button", {
        name: "bulk.print:1",
      })
      .closest(".flex-wrap");
    expect(group).toHaveClass("flex-wrap");
  });

  it("sticks below the app header, not under it", () => {
    renderBar();
    const bar = screen.getByText("bulk.selectedCount:3").closest(".sticky");
    expect(bar?.className).not.toContain("top-0");
    expect(bar?.className).toMatch(/top-\[calc\(3\.5rem\+/);
  });

  it("disables what the selection has nothing for", () => {
    renderBar({ draftCount: 0, printableCount: 0 });
    expect(
      screen.getByRole("button", { name: "Print as one PDF" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "bulk.confirmDrafts:0" }),
    ).toBeDisabled();
  });

  it("leaves a reader only the actions that are not writes", () => {
    renderBar({ canWrite: false });
    expect(
      screen.queryByRole("button", { name: /confirmDrafts/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /deleteDrafts/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "bulk.print:1" }),
    ).toBeInTheDocument();
  });
});
