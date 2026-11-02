import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";

import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { ModulesProvider } from "@/contexts/ModulesContext";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import { onePage } from "@/test/mocks/page";

import TemplatesPage from "./TemplatesPage";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
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

const template = {
  id: "tpl-1",
  name: "Standard Checkout",
  document_type: "CHECKOUT",
  body_html: "<p>Checkout protocol</p>",
  is_default: true,
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
};

const model = {
  id: "model-1",
  name: "XPS 15",
  brand: "Dell",
  image_url: null,
  description: "High-end laptop",
  category_id: null,
  category_name: null,
  equipment_meta: {},
};

beforeEach(() => {
  signInWith(["equipment:read", "equipment:write", "categories:read"]);
  server.use(
    http.get("/api/v1/equipment/templates", () =>
      HttpResponse.json(onePage([template])),
    ),
    http.get("/api/v1/equipment/templates/placeholders", () =>
      HttpResponse.json([]),
    ),
    http.get("/api/v1/equipment/models", () =>
      HttpResponse.json(onePage([model])),
    ),
    http.get("/api/v1/categories", () => HttpResponse.json(onePage([]))),
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
  return render(
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter>
          <PageHeaderHost>
            <TemplatesPage />
          </PageHeaderHost>
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>,
  );
}

async function openModels() {
  const user = userEvent.setup();
  renderPage();
  await screen.findByText("Standard Checkout");
  await user.click(screen.getByRole("tab", { name: /Equipment Models/ }));
  await screen.findByText("Dell XPS 15");
  return user;
}

/**
 * Deleting from either catalogue goes through a confirmation, and only a
 * confirmed one reaches the server. The failure caught: a delete wired
 * straight to the click, or a confirmation whose answer is ignored.
 */
describe("TemplatesPage — deleting asks first", () => {
  it("deletes a document template only once the reader confirms", async () => {
    const deleted = vi.fn();
    server.use(
      http.delete("/api/v1/equipment/templates/tpl-1", () => {
        deleted();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(
      await screen.findByRole("button", { name: "Delete Standard Checkout" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Delete template")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(deleted).toHaveBeenCalledTimes(1));
  });

  it("leaves a model alone when the confirmation is cancelled, and deletes it when confirmed", async () => {
    const deleted = vi.fn();
    server.use(
      http.delete("/api/v1/equipment/models/model-1", () => {
        deleted();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = await openModels();

    await user.click(screen.getByRole("button", { name: "Delete XPS 15" }));
    let dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
    expect(deleted).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Delete XPS 15" }));
    dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleted).toHaveBeenCalledTimes(1));
  });
});

describe("TemplatesPage — the model catalogue", () => {
  it("clones a model and says so", async () => {
    server.use(
      http.post("/api/v1/equipment/models/model-1/clone", () =>
        HttpResponse.json({ ...model, id: "model-2", name: "XPS 15 (copy)" }),
      ),
    );
    const user = await openModels();

    await user.click(screen.getByRole("button", { name: "Clone XPS 15" }));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Model cloned"),
    );
  });

  it("passes on why a clone was refused", async () => {
    server.use(
      http.post("/api/v1/equipment/models/model-1/clone", () =>
        HttpResponse.json({ detail: "Name already taken" }, { status: 409 }),
      ),
    );
    const user = await openModels();

    await user.click(screen.getByRole("button", { name: "Clone XPS 15" }));
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Name already taken"),
    );
  });

  it("creates a model from the header button and closes the editor", async () => {
    let body: Record<string, unknown> = {};
    server.use(
      http.post("/api/v1/equipment/models", async ({ request }) => {
        body = (await request.json()) as typeof body;
        return HttpResponse.json({ ...model, id: "model-9", name: "T14" });
      }),
    );
    const user = await openModels();

    await user.click(screen.getByRole("button", { name: "Create Model" }));
    const editor = await screen.findByRole("dialog");
    await user.type(within(editor).getByLabelText(/^Name/), "T14");
    await user.click(
      within(editor).getByRole("button", { name: "Create Model" }),
    );

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Model created"),
    );
    expect(body.name).toBe("T14");
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("saves an edited model to its own address and keeps the editor open on a refusal", async () => {
    let attempts = 0;
    let body: Record<string, unknown> = {};
    server.use(
      http.put("/api/v1/equipment/models/model-1", async ({ request }) => {
        attempts++;
        body = (await request.json()) as typeof body;
        if (attempts === 1) {
          return HttpResponse.json(
            { detail: "Brand is too long" },
            { status: 422 },
          );
        }
        return HttpResponse.json({ ...model, ...body });
      }),
    );
    const user = await openModels();

    await user.click(screen.getByRole("button", { name: "Edit XPS 15" }));
    const editor = await screen.findByRole("dialog");
    const name = within(editor).getByLabelText(/^Name/);
    await user.clear(name);
    await user.type(name, "XPS 15 2024");
    await user.click(within(editor).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    await user.click(within(editor).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Model updated"),
    );
    expect(body.name).toBe("XPS 15 2024");
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("says why a new model was refused", async () => {
    server.use(
      http.post("/api/v1/equipment/models", () =>
        HttpResponse.json({ detail: "Model exists" }, { status: 409 }),
      ),
    );
    const user = await openModels();

    await user.click(screen.getByRole("button", { name: "Create Model" }));
    const editor = await screen.findByRole("dialog");
    await user.type(within(editor).getByLabelText(/^Name/), "XPS 15");
    await user.click(
      within(editor).getByRole("button", { name: "Create Model" }),
    );

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Model exists"),
    );
  });
});

describe("TemplatesPage — the document templates", () => {
  it("copies the built-in layouts from the header", async () => {
    const seeded = vi.fn();
    server.use(
      http.post("/api/v1/equipment/templates/seed-defaults", () => {
        seeded();
        return HttpResponse.json([template], { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Standard Checkout");

    await user.click(
      screen.getByRole("button", { name: "Copy the built-in layouts" }),
    );
    await waitFor(() => expect(seeded).toHaveBeenCalledTimes(1));
  });

  it("opens the editor on a template, and on a blank one from the header", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(
      await screen.findByRole("button", { name: "Edit Standard Checkout" }),
    );
    let editor = await screen.findByRole("dialog");
    expect(within(editor).getByDisplayValue("Standard Checkout")).toBeVisible();
    await user.click(within(editor).getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: "Add Template" }));
    editor = await screen.findByRole("dialog");
    expect(
      within(editor).queryByDisplayValue("Standard Checkout"),
    ).not.toBeInTheDocument();
  });
});
