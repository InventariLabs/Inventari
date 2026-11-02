import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { useCallback, useState, type ReactNode } from "react";
import CategoriesPage from "./CategoriesPage";
import { server } from "@/test/mocks/server";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { signInWith, signOut } from "@/test/auth";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

// The page owns when the form and the group sheet open, with which category,
// and what it does once they close; their own insides have tests of their own.
vi.mock("@/modules/inventory/components/CategoryFormModal", () => ({
  CategoryFormModal: ({
    isOpen,
    editingCategory,
    onClose,
  }: {
    isOpen: boolean;
    editingCategory: { name: string } | null;
    onClose: () => void;
  }) =>
    isOpen ? (
      <div role="dialog" aria-label="category form">
        <span>editing: {editingCategory?.name ?? "new"}</span>
        <button onClick={onClose}>close form</button>
      </div>
    ) : null,
}));

vi.mock("@/modules/inventory/components/CategoryGroupSheet", () => ({
  CategoryGroupSheet: ({
    group,
    onClose,
    onDone,
  }: {
    group: string;
    onClose: () => void;
    onDone: (newName?: string) => void;
  }) => (
    <div role="dialog" aria-label="group sheet">
      <span>group: {group}</span>
      <button onClick={onClose}>close sheet</button>
      <button onClick={() => onDone("CELLAR")}>rename to cellar</button>
      <button onClick={() => onDone()}>dissolve group</button>
    </div>
  ),
}));

const dairy = {
  id: "cat-1",
  name: "Dairy",
  icon: "Milk",
  group_label: "FRIDGE",
  is_active: true,
  sort_order: 1,
  field_definitions: [],
  items_count: 0,
};
const retired = {
  ...dairy,
  id: "cat-2",
  name: "Retired Snacks",
  group_label: "PANTRY",
  is_active: false,
};

/** The shell's header, standing in: what the page publishes is rendered. */
function HeaderHost({ children }: { children: ReactNode }) {
  const [actions, setActions] = useState<ReactNode>(null);
  const setHeader = useCallback(
    (data: { actions?: ReactNode }) => setActions(data.actions ?? null),
    [],
  );
  return (
    <PageHeaderContext.Provider value={{ data: {}, setHeader }}>
      <header>{actions}</header>
      {children}
    </PageHeaderContext.Provider>
  );
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/categories"]}>
        <HeaderHost>
          <Routes>
            <Route path="/categories" element={<CategoriesPage />} />
            <Route path="/settings" element={<p>settings page</p>} />
          </Routes>
        </HeaderHost>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function serve(rows: unknown[]) {
  server.use(
    http.get("/api/v1/categories", () => HttpResponse.json(onePage(rows))),
  );
}

/**
 * The register's writes and the dialogs around them: a delete or restore
 * that reports nothing (or reports success over a refusal), an edit button
 * that opens the form on the wrong category, a group rename that leaves the
 * filter on a group that no longer exists, a page-size change that keeps the
 * reader on a page past the end.
 */
describe("CategoriesPage — card actions, dialogs and paging", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    signInWith(["categories:read", "categories:write"]);
    serve([dairy, retired]);
  });

  afterEach(() => signOut());

  it("deletes an empty category after the confirmation and says so", async () => {
    const deleted = vi.fn();
    server.use(
      http.delete("/api/v1/categories/:id", ({ params }) => {
        deleted(params.id);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Dairy");

    await user.click(screen.getByRole("button", { name: /^delete$/i }));
    const dialog = screen.getByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: /^delete$/i }));

    await waitFor(() => expect(deleted).toHaveBeenCalledWith("cat-1"));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Category deleted!"),
    );
  });

  it("reports the server's refusal of a delete", async () => {
    server.use(
      http.delete("/api/v1/categories/:id", () =>
        HttpResponse.json({ detail: "Still in use" }, { status: 400 }),
      ),
    );
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Dairy");

    await user.click(screen.getByRole("button", { name: /^delete$/i }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: /^delete$/i,
      }),
    );

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("restores a retired category by switching it back on", async () => {
    let body: unknown;
    server.use(
      http.put("/api/v1/categories/cat-2", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ ...retired, is_active: true });
      }),
    );
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Retired Snacks");

    await user.click(screen.getByRole("button", { name: "Restore" }));

    await waitFor(() => expect(body).toEqual({ is_active: true }));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Category restored"),
    );
  });

  it("reports a failed restore", async () => {
    server.use(
      http.put("/api/v1/categories/cat-2", () =>
        HttpResponse.json({ detail: "nope" }, { status: 400 }),
      ),
    );
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Retired Snacks");

    await user.click(screen.getByRole("button", { name: "Restore" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });

  it("opens the form on the card's own category, and fresh from the header", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Dairy");

    await user.click(screen.getAllByRole("button", { name: "Edit" })[0]!);
    expect(screen.getByText("editing: Dairy")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "close form" }));
    expect(screen.queryByRole("dialog", { name: "category form" })).toBeNull();

    await user.click(screen.getByRole("button", { name: /add category/i }));
    expect(screen.getByText("editing: new")).toBeInTheDocument();
  });

  it("offers the first category from the empty register", async () => {
    serve([]);
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("No categories");
    // The empty state's own offer, under the header's.
    const adds = screen.getAllByRole("button", { name: /add category/i });
    expect(adds).toHaveLength(2);
    await user.click(adds[1]!);
    expect(screen.getByText("editing: new")).toBeInTheDocument();
  });

  it("manages the filtered group and follows its rename", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Dairy");

    await user.click(screen.getByRole("combobox", { name: "Group" }));
    await user.click(await screen.findByRole("option", { name: /fridge/i }));
    await user.click(
      screen.getByRole("button", { name: /rename or remove this group/i }),
    );
    expect(screen.getByText("group: FRIDGE")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "close sheet" }));
    expect(screen.queryByRole("dialog", { name: "group sheet" })).toBeNull();

    await user.click(
      screen.getByRole("button", { name: /rename or remove this group/i }),
    );
    await user.click(screen.getByRole("button", { name: "dissolve group" }));
    expect(screen.queryByRole("dialog", { name: "group sheet" })).toBeNull();
    // A dissolved group leaves the filter on "All groups", where both show.
    expect(screen.getByText("Retired Snacks")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /rename or remove this group/i }),
    ).not.toBeInTheDocument();
  });

  it("follows a renamed group with the filter", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Dairy");

    await user.click(screen.getByRole("combobox", { name: "Group" }));
    await user.click(await screen.findByRole("option", { name: /fridge/i }));
    await user.click(
      screen.getByRole("button", { name: /rename or remove this group/i }),
    );
    await user.click(screen.getByRole("button", { name: "rename to cellar" }));

    // The filter now names the new group, which no card carries yet.
    expect(screen.queryByText("Dairy")).toBeNull();
    expect(
      screen.getByRole("button", { name: /rename or remove this group/i }),
    ).toBeInTheDocument();
  });

  it("opens the settings from a register the module-data policy emptied", async () => {
    server.use(
      http.get("/api/v1/categories", ({ request }) => {
        const url = new URL(request.url);
        return HttpResponse.json(
          onePage(
            url.searchParams.get("exclude_module_contexts") === "true"
              ? []
              : [{ ...dairy, context_tag: "equipment" }],
          ),
        );
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(
      await screen.findByRole("button", { name: /open settings/i }),
    );
    expect(await screen.findByText("settings page")).toBeInTheDocument();
  });

  it("jumps to a typed page and goes back to the first on a new page size", async () => {
    serve(
      Array.from({ length: 60 }, (_, i) => ({
        ...dairy,
        id: `cat-${i}`,
        name: `Category ${String(i).padStart(2, "0")}`,
      })),
    );
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Category 00");

    const page = screen.getByRole("spinbutton", { name: /page/i });
    await user.clear(page);
    await user.type(page, "3{Enter}");
    expect(await screen.findByText("Category 48")).toBeInTheDocument();
    expect(screen.queryByText("Category 00")).toBeNull();

    await user.selectOptions(
      screen.getByRole("combobox", { name: /rows per page/i }),
      "96",
    );
    expect(await screen.findByText("Category 00")).toBeInTheDocument();
    expect(screen.getByText("Category 59")).toBeInTheDocument();
  });
});
