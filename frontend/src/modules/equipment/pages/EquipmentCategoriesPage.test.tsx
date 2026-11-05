import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { ModulesProvider } from "@/contexts/ModulesContext";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import { onePage } from "@/test/mocks/page";

import EquipmentCategoriesPage from "./EquipmentCategoriesPage";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const CATEGORIES = [
  {
    id: "cat-1",
    name: "Monitors",
    code: null,
    context_tag: "equipment",
    items_count: 0,
    field_definitions: [],
  },
  // A grocery category in the same organization: not this screen's to list.
  {
    id: "cat-2",
    name: "Dairy",
    code: null,
    context_tag: null,
    items_count: 4,
    field_definitions: [],
  },
];

beforeEach(() => {
  signInWith(["equipment:read", "categories:read", "categories:write"]);
  server.use(
    http.get("/api/v1/categories", () =>
      HttpResponse.json(onePage(CATEGORIES)),
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
      {data.actions ? <div>{data.actions}</div> : null}
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
      <ModulesProvider>
        <MemoryRouter>
          <PageHeaderHost>
            <EquipmentCategoriesPage />
          </PageHeaderHost>
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

/**
 * The category screen lists the module's categories and acts on them
 * through the shared form and a confirmation. The failures caught: a delete
 * sent without the confirmation (or after a cancel), and the edit form
 * opening empty instead of on the category that was clicked.
 */
describe("EquipmentCategoriesPage", () => {
  it("lists only the module's categories", async () => {
    renderPage();
    expect((await screen.findAllByText("Monitors")).length).toBeGreaterThan(0);
    expect(screen.queryByText("Dairy")).not.toBeInTheDocument();
  });

  it("deletes a category only once the confirmation is accepted", async () => {
    const deleted = vi.fn();
    server.use(
      http.delete("/api/v1/categories/cat-1", () => {
        deleted();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = renderPage();

    const [deleteButton] = await screen.findAllByRole("button", {
      name: "Delete Monitors",
    });
    await user.click(deleteButton);
    let dialog = await screen.findByRole("alertdialog");
    expect(
      within(dialog).getByText(/^Delete category "Monitors"\?/),
    ).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
    expect(deleted).not.toHaveBeenCalled();

    await user.click(deleteButton);
    dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleted).toHaveBeenCalledTimes(1));
  });

  it("names what goes with the category: its field definitions and the assets that block it", async () => {
    server.use(
      http.get("/api/v1/categories", () =>
        HttpResponse.json(
          onePage([
            {
              ...CATEGORIES[0],
              items_count: 3,
              field_definitions: [{ key: "a" }, { key: "b" }],
            },
          ]),
        ),
      ),
    );
    const user = renderPage();

    const [deleteButton] = await screen.findAllByRole("button", {
      name: "Delete Monitors",
    });
    await user.click(deleteButton);
    const dialog = await screen.findByRole("alertdialog");

    expect(
      within(dialog).getByText(
        /This permanently removes its 2 field definitions\./,
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        /3 assets are filed under it, so it cannot be deleted/,
      ),
    ).toBeInTheDocument();
  });

  it("opens the form on the clicked category, and empty from the header", async () => {
    const user = renderPage();

    const [editButton] = await screen.findAllByRole("button", {
      name: "Edit Monitors",
    });
    await user.click(editButton);
    expect(await screen.findByText("Edit Category")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Monitors")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.queryByText("Edit Category")).not.toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: "Add Category" }));
    expect(await screen.findByText("Add New Category")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("Monitors")).not.toBeInTheDocument();
  });

  it("opens Add Category empty after a cancel and after a save", async () => {
    server.use(
      http.post("/api/v1/categories", () =>
        HttpResponse.json({ id: "cat-new", name: "Docks" }, { status: 201 }),
      ),
    );
    const user = renderPage();
    const openForm = async () => {
      await user.click(
        await screen.findByRole("button", { name: "Add Category" }),
      );
      return screen.findByRole("textbox", { name: /category name/i });
    };
    const formClosed = () =>
      waitFor(() =>
        expect(screen.queryByText("Add New Category")).not.toBeInTheDocument(),
      );

    await user.type(await openForm(), "Draft cat");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await formClosed();

    const afterCancel = await openForm();
    expect(afterCancel).toHaveValue("");

    await user.type(afterCancel, "Docks");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await formClosed();

    expect(await openForm()).toHaveValue("");
  });
});
