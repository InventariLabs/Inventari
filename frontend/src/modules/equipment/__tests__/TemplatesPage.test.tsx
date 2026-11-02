import React from "react";
import {
  render,
  waitFor,
  screen,
  act,
  fireEvent,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import {
  describe,
  it,
  expect,
  vi,
  beforeEach,
  beforeAll,
  afterAll,
} from "vitest";
import TemplatesPage from "../pages/TemplatesPage";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { onePage } from "@/test/mocks/page";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { withLanguage } from "@/test/mocks/i18n";

const origRAF = globalThis.requestAnimationFrame;
const origCAF = globalThis.cancelAnimationFrame;
beforeAll(() => {
  let rafId = 0;
  globalThis.requestAnimationFrame = (cb: FrameRequestCallback) => {
    rafId++;
    setTimeout(() => cb(Date.now()), 0);
    return rafId;
  };
  globalThis.cancelAnimationFrame = () => {};
});
afterAll(() => {
  globalThis.requestAnimationFrame = origRAF;
  globalThis.cancelAnimationFrame = origCAF;
});

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({
    setHeader: vi.fn(),
  }),
}));

// The page gates its write actions on this; without a permission context it
// answers "no", and the actions under test are write actions.
vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => true,
  useCanManage: () => true,
}));

vi.mock("@/hooks/useConfirm", () => ({
  useConfirm: () => ({
    confirm: vi.fn(),
  }),
}));

const mockTemplates = [
  {
    id: "tpl-1",
    name: "Standard Checkout",
    document_type: "CHECKOUT",
    body_html: "<p>Checkout protocol</p>",
    is_default: true,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
  },
];

const mockPlaceholders = [
  { key: "{{item_name}}", label: "Item Name" },
  { key: "{{assignee}}", label: "Assignee" },
];

const mockModels = [
  {
    id: "model-1",
    name: "XPS 15",
    brand: "Dell",
    image_url: null,
    description: "High-end laptop",
    category_id: "cat-1",
    category_name: "Laptops",
    equipment_meta: { specs: { ram: "16GB" } },
  },
  {
    id: "model-2",
    name: "ThinkPad T14",
    brand: "Lenovo",
    image_url: null,
    description: null,
    category_id: null,
    category_name: null,
    equipment_meta: {},
  },
];

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <BrowserRouter>{children}</BrowserRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
};

function switchTab(tabName: RegExp) {
  const tab = screen.getByRole("tab", { name: tabName });
  act(() => {
    fireEvent.mouseDown(tab, { button: 0, ctrlKey: false });
  });
}

describe("TemplatesPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.resetHandlers();
    server.use(
      http.get("/api/v1/equipment/templates", () =>
        HttpResponse.json(onePage(mockTemplates)),
      ),
      http.get("/api/v1/equipment/templates/placeholders", () =>
        HttpResponse.json(mockPlaceholders),
      ),
      http.get("/api/v1/equipment/models", () =>
        HttpResponse.json(onePage(mockModels)),
      ),
    );
  });

  it("renders document templates by default", async () => {
    render(<TemplatesPage />, { wrapper: createWrapper() });

    await waitFor(
      () => {
        expect(screen.getByText("Standard Checkout")).toBeInTheDocument();
      },
      { timeout: 5000 },
    );
  });

  it("switches to models tab and renders model cards", async () => {
    render(<TemplatesPage />, { wrapper: createWrapper() });

    await act(async () => {
      await new Promise((r) => setTimeout(r, 200));
    });

    switchTab(/Equipment Models/i);

    await waitFor(
      () => {
        expect(screen.getByText("Dell XPS 15")).toBeInTheDocument();
      },
      { timeout: 5000 },
    );
    expect(screen.getByText("Lenovo ThinkPad T14")).toBeInTheDocument();
  });

  it("shows empty state when no models exist", async () => {
    server.use(
      http.get("/api/v1/equipment/models", () =>
        HttpResponse.json(onePage([])),
      ),
    );
    render(<TemplatesPage />, { wrapper: createWrapper() });

    switchTab(/Equipment Models/i);

    await waitFor(
      () => {
        expect(screen.getByText(/No equipment models/i)).toBeInTheDocument();
      },
      { timeout: 5000 },
    );
  });
});

/**
 * A copy belongs to the organization and nothing rewrites it, so the only
 * thing it cannot know on its own is that the built-in it came from has moved
 * on since. Documents and purchase orders say it. Equipment did not — the
 * list endpoint never passed the built-ins, so `source_outdated` was never
 * computed, and the screen used a second TemplateCard that had no branch for
 * it either.
 */
describe("TemplatesPage — an equipment protocol whose built-in moved on", () => {
  const copy = {
    ...mockTemplates[0],
    source_builtin: "Standard Checkout",
    source_outdated: false,
  };

  const serve = (template: Record<string, unknown>) => {
    server.resetHandlers();
    server.use(
      http.get("/api/v1/equipment/templates", () =>
        HttpResponse.json(onePage([template])),
      ),
      http.get("/api/v1/equipment/templates/placeholders", () =>
        HttpResponse.json(mockPlaceholders),
      ),
      http.get("/api/v1/equipment/models", () =>
        HttpResponse.json(onePage(mockModels)),
      ),
    );
  };

  it("says nothing while the copy still matches the built-in", async () => {
    serve(copy);
    render(<TemplatesPage />, { wrapper: createWrapper() });

    await screen.findByText("Standard Checkout", undefined, { timeout: 5000 });
    expect(
      screen.queryByTestId("template-outdated-note"),
    ).not.toBeInTheDocument();
  });

  it("marks the copy and offers the current built-in alongside", async () => {
    const refreshed = vi.fn();
    serve({ ...copy, source_outdated: true });
    server.use(
      http.post("/api/v1/equipment/templates/tpl-1/refresh-copy", () => {
        refreshed();
        return HttpResponse.json(
          { ...copy, id: "tpl-2", name: "Standard Checkout (2)" },
          { status: 201 },
        );
      }),
    );
    render(<TemplatesPage />, { wrapper: createWrapper() });

    expect(
      await screen.findByTestId("template-outdated-note", undefined, {
        timeout: 5000,
      }),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", {
        name: /copy the current built-in alongside/i,
      }),
    );
    await waitFor(() => expect(refreshed).toHaveBeenCalled());
  });
});

describe("TemplatesPage — the protocol editor's symbols", () => {
  it("describes each symbol in the reader's language", async () => {
    // The API describes symbols in English only; this editor passed the
    // dialog no catalogue, so a Polish reader hovering a symbol read
    // "Asset name".
    server.resetHandlers();
    server.use(
      http.get("/api/v1/equipment/templates", () =>
        HttpResponse.json(onePage(mockTemplates)),
      ),
      http.get("/api/v1/equipment/templates/placeholders", () =>
        HttpResponse.json([
          { key: "{{item_name}}", description: "Asset name" },
        ]),
      ),
      http.get("/api/v1/equipment/models", () =>
        HttpResponse.json(onePage(mockModels)),
      ),
    );

    await withLanguage("pl", async () => {
      render(<TemplatesPage />, { wrapper: createWrapper() });

      fireEvent.click(
        await screen.findByRole(
          "button",
          { name: "Edytuj: Standard Checkout" },
          { timeout: 5000 },
        ),
      );

      const symbol = (await screen.findByText("{{item_name}}")).closest(
        "button",
      );
      expect(symbol).toHaveAttribute("title", "Nazwa zasobu");
      expect(symbol).toHaveTextContent("Nazwa zasobu");
    });
  });
});
