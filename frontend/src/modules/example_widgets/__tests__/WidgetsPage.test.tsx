import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { createElement } from "react";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { signInWith, signOut } from "@/test/auth";
import WidgetsPage from "../pages/WidgetsPage";

/** Page tests render bare of the shell — the header hook needs its provider,
 * or every mount logs the wiring warning 15 times a run. */
const pageHeader = { data: {}, setHeader: () => {} };

vi.mock("../hooks/useWidgets", () => ({
  useWidgets: vi.fn(),
  useCreateWidget: vi.fn(),
  useUpdateWidget: vi.fn(),
  useDeleteWidget: vi.fn(),
}));

import {
  useWidgets,
  useCreateWidget,
  useUpdateWidget,
  useDeleteWidget,
} from "../hooks/useWidgets";

const mockWidget = {
  id: "w-1",
  name: "Gadget",
  color: "red",
  quantity: 3,
};

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    createElement(
      PageHeaderContext.Provider,
      { value: pageHeader },
      createElement(
        QueryClientProvider,
        { client: qc },
        createElement(WidgetsPage),
      ),
    ),
  );
}

function setupHooks(
  widgets: (typeof mockWidget)[] | undefined = [],
  state: { isLoading?: boolean; isError?: boolean } = {},
) {
  const mutate = vi.fn();
  vi.mocked(useWidgets).mockReturnValue({
    data: widgets && {
      items: widgets,
      total: widgets.length,
      limit: 100,
      offset: 0,
      has_more: false,
    },
    isLoading: state.isLoading ?? false,
    isError: state.isError ?? false,
    refetch: vi.fn(),
  } as never);
  vi.mocked(useCreateWidget).mockReturnValue({
    mutate,
    mutateAsync: vi.fn(),
  } as never);
  vi.mocked(useUpdateWidget).mockReturnValue({
    mutate,
    mutateAsync: vi.fn(),
  } as never);
  vi.mocked(useDeleteWidget).mockReturnValue({
    mutate,
    mutateAsync: vi.fn(),
  } as never);
  return { mutate };
}

// The page hides every write from an account that may not write, so a spec
// about the buttons has to say who is looking at them. This is the shape to
// copy: sign in with the keys the test needs, and nothing else.
beforeEach(() => {
  vi.clearAllMocks();
  signInWith(["example_widgets:read", "example_widgets:write"]);
});

afterEach(() => {
  signOut();
});

describe("WidgetsPage", () => {
  it("shows the server's sentence when a create is refused", () => {
    setupHooks([]);
    const refusal = new AxiosError(
      "Request failed",
      "ERR_BAD_REQUEST",
      undefined,
      {},
      {
        status: 409,
        data: {
          detail: { code: "WIDGET_EXISTS", message: "Widget already exists." },
        },
      } as never,
    );
    vi.mocked(useCreateWidget).mockReturnValue({
      mutate: vi.fn(),
      isError: true,
      error: refusal,
    } as never);
    renderPage();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Widget already exists.",
    );
  });

  it("shows the same spinner as the rest of the app while loading", () => {
    setupHooks(undefined, { isLoading: true });
    renderPage();
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
  });

  it("offers a way back when the list cannot be read", () => {
    setupHooks(undefined, { isError: true });
    renderPage();
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });

  it("renders empty state when no widgets", () => {
    setupHooks([]);
    renderPage();
    expect(
      screen.getByText("No widgets yet. Create your first one!"),
    ).toBeInTheDocument();
  });

  it("renders widget cards when data is present", () => {
    setupHooks([mockWidget]);
    renderPage();
    expect(screen.getByText("Gadget")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    // The stored key is shown by its translated name, not raw.
    expect(screen.getByText("Color: Red")).toBeInTheDocument();
  });

  it("offers colors as a closed set instead of free text", () => {
    setupHooks([]);
    renderPage();

    const color = screen.getByLabelText("Color");
    expect(color.tagName).toBe("SELECT");
    expect(
      Array.from(color.querySelectorAll("option")).map((o) => o.value),
    ).toEqual(["blue", "green", "amber", "red", "violet", "slate"]);
  });

  it("names both form fields for a screen reader", () => {
    setupHooks([]);
    renderPage();
    expect(screen.getByLabelText("Name")).toBeInTheDocument();
    expect(screen.getByLabelText("Color")).toBeInTheDocument();
  });

  it("calls createWidget on form submit", () => {
    const { mutate } = setupHooks([]);
    renderPage();

    const input = screen.getByLabelText("Name");
    fireEvent.change(input, { target: { value: "New Widget" } });
    const buttons = screen.getAllByRole("button");
    const addButton = buttons.find((b) => b.textContent === "Add Widget")!;
    fireEvent.click(addButton);

    expect(mutate).toHaveBeenCalledWith(
      { name: "New Widget", color: "blue" },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });

  it("creates with the colour that was picked, and starts the form over once it is saved", () => {
    // A form that kept "Red" and the old name after a save would make the
    // next widget a copy of the last one.
    const { mutate } = setupHooks([]);
    renderPage();

    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "Fire widget" },
    });
    fireEvent.change(screen.getByLabelText("Color"), {
      target: { value: "red" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add Widget" }));

    expect(mutate).toHaveBeenCalledWith(
      { name: "Fire widget", color: "red" },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );

    act(() => mutate.mock.calls[0][1].onSuccess());

    expect(screen.getByLabelText("Name")).toHaveValue("");
    expect(screen.getByLabelText("Color")).toHaveValue("blue");
  });

  it("creates on Enter in the name field, and ignores Enter on an empty name", () => {
    const { mutate } = setupHooks([]);
    renderPage();

    const name = screen.getByLabelText("Name");
    fireEvent.keyDown(name, { key: "Enter" });
    expect(mutate).not.toHaveBeenCalled();

    fireEvent.change(name, { target: { value: "  Keyed  " } });
    fireEvent.keyDown(name, { key: "Enter" });

    expect(mutate).toHaveBeenCalledWith(
      { name: "Keyed", color: "blue" },
      expect.anything(),
    );
  });

  it("asks before deleting, in the app's own dialog", () => {
    const { mutate } = setupHooks([mockWidget]);
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(mutate).not.toHaveBeenCalled();
    expect(screen.getByText("Delete this widget?")).toBeInTheDocument();

    const confirm = screen
      .getAllByRole("button", { name: "Delete" })
      .find((b) => b.closest("[role='alertdialog']"))!;
    fireEvent.click(confirm);
    expect(mutate).toHaveBeenCalledWith("w-1");
  });

  it("deletes nothing when the question is declined", () => {
    const { mutate } = setupHooks([mockWidget]);
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(mutate).not.toHaveBeenCalled();
  });

  it("increments quantity via + button", () => {
    const { mutate } = setupHooks([mockWidget]);
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "Increase quantity" }));

    expect(mutate).toHaveBeenCalledWith({
      id: "w-1",
      data: { quantity: 4 },
    });
  });

  it("decrements quantity via - button (min 0)", () => {
    const { mutate } = setupHooks([mockWidget]);
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "Decrease quantity" }));

    expect(mutate).toHaveBeenCalledWith({
      id: "w-1",
      data: { quantity: 2 },
    });
  });

  it("does not decrement below 0", () => {
    const { mutate } = setupHooks([{ ...mockWidget, quantity: 0 }]);
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "Decrease quantity" }));

    expect(mutate).toHaveBeenCalledWith({
      id: "w-1",
      data: { quantity: 0 },
    });
  });
});

describe("WidgetsPage, for an account that may only read", () => {
  beforeEach(() => {
    signInWith(["example_widgets:read"]);
  });

  it("keeps the list readable", () => {
    setupHooks([mockWidget]);
    renderPage();

    expect(screen.getByText("Gadget")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("offers no write at all — not the form, not the steppers, not delete", () => {
    setupHooks([mockWidget]);
    renderPage();

    // All of them, not the first one somebody thought of: changing a quantity
    // is a write like any other, and the API refuses it either way.
    expect(screen.queryByLabelText("Name")).toBeNull();
    expect(screen.queryByRole("button", { name: "Add Widget" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Increase quantity" }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Decrease quantity" }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });

  it("says why the screen has no buttons on it", () => {
    setupHooks([mockWidget]);
    renderPage();

    // A page that hides its actions and says nothing reads as broken rather
    // than as a boundary.
    expect(
      screen.getByText("You can view this, not change it"),
    ).toBeInTheDocument();
  });
});
