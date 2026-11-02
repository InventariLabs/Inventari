import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, it, expect } from "vitest";
import { MemoryRouter, useLocation } from "react-router-dom";
import { useFormGuardStore } from "@/store/formGuardStore";
import { PageHeader } from "./PageHeader";

function renderHeader(actions?: React.ReactNode) {
  return render(
    <MemoryRouter>
      <PageHeader title="Recipes" actions={actions} />
    </MemoryRouter>,
  );
}

describe("PageHeader actions", () => {
  /**
   * Callers build the action group as one `flex … shrink-0` div of their
   * own, and below `sm` this wrapper is full-width: a group wider than a
   * phone then ran past the root's overflow-x-hidden and was cut off
   * unreachable — measured on /recipes at 320px in DE, the group was 331px
   * in a 296px row ("Neues Rezept" ending at 343px). The wrapper lends
   * every direct child shrink and wrap, so a group that does not fit folds
   * its buttons instead of leaving the screen — the same class fix the
   * ListControlBar row got.
   */
  it("lets an overwide action group fold its buttons, not leave the screen", () => {
    renderHeader(
      <div className="flex items-center gap-2 shrink-0 ml-auto">
        <button type="button">Neues Rezept</button>
        <button type="button">CSV/JSON importieren</button>
      </div>,
    );

    const group = screen.getByRole("button", {
      name: "Neues Rezept",
    }).parentElement!;
    const wrapper = group.parentElement!;
    expect(wrapper.className).toContain("[&>*]:shrink");
    expect(wrapper.className).toContain("[&>*]:flex-wrap");
  });

  it("renders a single action without lending it anything new", () => {
    renderHeader(<button type="button">Add</button>);
    expect(screen.getByRole("button", { name: "Add" })).toBeInTheDocument();
  });
});

function Where() {
  return <output data-testid="where">{useLocation().pathname}</output>;
}

function renderBack(entries: string[], index: number, backTo = "/orders") {
  return render(
    <MemoryRouter initialEntries={entries} initialIndex={index}>
      <PageHeader title="Order 42" backTo={backTo} />
      <Where />
    </MemoryRouter>,
  );
}

describe("PageHeader back arrow", () => {
  afterEach(() => act(() => useFormGuardStore.getState().setDirtyForm(null)));

  it("steps back through history when the reader came from another screen", async () => {
    renderBack(["/stock", "/orders/42"], 1);

    await userEvent.click(screen.getByRole("button", { name: "Back" }));

    // History wins over `backTo`, so the arrow behaves like the browser button.
    expect(screen.getByTestId("where")).toHaveTextContent("/stock");
  });

  it("falls back to the parent screen on a deep link with no history", async () => {
    renderBack(["/orders/42"], 0);

    await userEvent.click(screen.getByRole("button", { name: "Back" }));

    expect(screen.getByTestId("where")).toHaveTextContent(/^\/orders$/);
  });

  it("asks before leaving a form with unsaved work, and stays put on Cancel", async () => {
    renderBack(["/orders/42"], 0);
    act(() => useFormGuardStore.getState().setDirtyForm("The order form"));

    await userEvent.click(screen.getByRole("button", { name: "Back" }));

    expect(screen.getByTestId("where")).toHaveTextContent("/orders/42");
    await userEvent.click(
      await screen.findByRole("button", { name: "Cancel" }),
    );
    expect(screen.getByTestId("where")).toHaveTextContent("/orders/42");
  });

  it("leaves once the reader confirms the unsaved work may go", async () => {
    renderBack(["/orders/42"], 0);
    act(() => useFormGuardStore.getState().setDirtyForm("The order form"));

    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    await userEvent.click(
      await screen.findByRole("button", { name: "Leave anyway" }),
    );

    expect(screen.getByTestId("where")).toHaveTextContent(/^\/orders$/);
  });
});
