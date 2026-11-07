import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import { onePage } from "@/test/mocks/page";

import AddEquipmentPage from "./AddEquipmentPage";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/contexts/ModulesContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ModulesContext")>()),
  useModules: () => ({
    enabledModules: ["equipment"],
    isModuleEnabled: () => true,
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

const WORKSTATIONS = {
  id: "cat-ws",
  name: "Workstations",
  code: null,
  context_tag: "equipment",
  field_definitions: [
    { key: "cpu", label: "Processor", type: "text", visible: true },
    // Owned by the purchase card; the category must not draw it twice.
    { key: "warranty_until", label: "Warranty", type: "date", visible: true },
    { key: "secret", label: "Hidden note", type: "text", visible: false },
  ],
};

let categoryReads: number;

beforeEach(() => {
  categoryReads = 0;
  signInWith([
    "equipment:read",
    "equipment:write",
    "items:read",
    "items:write",
    "locations:read",
    "locations:write",
    "categories:read",
  ]);
  server.use(
    http.get("/api/v1/categories", () => {
      categoryReads++;
      return HttpResponse.json(onePage([WORKSTATIONS]));
    }),
    http.get("/api/v1/locations", () =>
      HttpResponse.json(
        onePage([{ id: "loc-1", name: "Server Room", items_count: 0 }]),
      ),
    ),
    http.get("/api/v1/equipment/models", () => HttpResponse.json(onePage([]))),
    http.get("/api/v1/organizations/my", () =>
      HttpResponse.json({ id: "org-1", name: "Org", currency: "EUR" }),
    ),
  );
});

afterEach(() => {
  signOut();
});

function PageHeaderHost({ children }: { children: React.ReactNode }) {
  const [data, setData] = React.useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
      {children}
    </PageHeaderContext.Provider>
  );
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/equipment/add"]}>
        <PageHeaderHost>
          <Routes>
            <Route path="/equipment/add" element={<AddEquipmentPage />} />
            <Route path="/equipment/assets" element={<p>the asset list</p>} />
          </Routes>
        </PageHeaderHost>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

/**
 * The add form grows with the chosen category, switches to a batch of
 * serials, and leaves for the list on Cancel. The failures caught: a
 * category's own fields never shown (or the dedicated date field drawn
 * twice, or a hidden one shown), a batch mode that still offers the single
 * save, and a failed picker list whose retry asks for nothing.
 */
describe("AddEquipmentPage — the form around the record", () => {
  it("shows the chosen category's visible fields, once each", async () => {
    const user = renderPage();

    const category = await screen.findByLabelText(/^Category/);
    await waitFor(() =>
      expect(
        screen.getByRole("option", { name: "Workstations" }),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByLabelText("Processor")).not.toBeInTheDocument();

    await user.selectOptions(category, "cat-ws");
    expect(await screen.findByLabelText("Processor")).toBeInTheDocument();
    expect(screen.queryByLabelText("Hidden note")).not.toBeInTheDocument();
    // The purchase card's own field, and no second one from the category.
    expect(
      screen.getAllByText("Warranty Until", { selector: "label" }),
    ).toHaveLength(1);
  });

  it("trades the single save for the serials panel in batch mode", async () => {
    const user = renderPage();
    await screen.findByLabelText(/^Category/);
    expect(
      screen.getByRole("button", { name: /Save Asset/ }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /Batch/ }));
    expect(
      screen.queryByRole("button", { name: /Save Asset/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Paste list" })).toBeInTheDocument();

    // The panel's own Cancel leaves the form for the list.
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await screen.findByText("the asset list")).toBeInTheDocument();
  });

  // The location field searches the server itself and says in its own panel
  // when a search failed; the page-level retry is left with the categories.
  it("asks for the categories again when they failed to load", async () => {
    server.use(
      http.get("/api/v1/categories", () => {
        categoryReads++;
        return HttpResponse.json({}, { status: 500 });
      }),
    );
    const user = renderPage();

    await screen.findByText(/Categories or locations could not be loaded/);
    const before = categoryReads;
    await user.click(screen.getByRole("button", { name: /try again/i }));

    await waitFor(() => expect(categoryReads).toBeGreaterThan(before));
    expect(screen.getByRole("button", { name: /Save Asset/ })).toBeDisabled();
  });

  it("opens the quick location form beside the location picker and closes it", async () => {
    const user = renderPage();
    await screen.findByLabelText(/^Category/);

    await user.click(screen.getByRole("button", { name: "Add Location" }));
    const dialog = await screen.findByRole("dialog", { name: "Add Location" });
    await user.click(
      within(dialog).getByText("Cancel", { selector: "button" }),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Add Location" }),
      ).not.toBeInTheDocument(),
    );
  });
});

describe("AddEquipmentPage — a read-only account", () => {
  function renderAt(path: string) {
    signInWith(["equipment:read"]);
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[path]}>
          <PageHeaderHost>
            <Routes>
              <Route path="/equipment/add" element={<AddEquipmentPage />} />
              <Route
                path="/equipment/:id/edit"
                element={<AddEquipmentPage />}
              />
              <Route path="/equipment/:id" element={<p>the asset card</p>} />
              <Route path="/equipment" element={<p>the register</p>} />
            </Routes>
          </PageHeaderHost>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    return userEvent.setup();
  }

  it("is taken from the edit form to the asset it may look at", async () => {
    const user = renderAt("/equipment/eq-1/edit");
    expect(screen.getByText(/you can view this/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open the asset" }));
    expect(await screen.findByText("the asset card")).toBeInTheDocument();
  });

  it("is taken from the add form back to the register", async () => {
    const user = renderAt("/equipment/add");
    await user.click(screen.getByRole("button", { name: "Back to list" }));
    expect(await screen.findByText("the register")).toBeInTheDocument();
  });
});
