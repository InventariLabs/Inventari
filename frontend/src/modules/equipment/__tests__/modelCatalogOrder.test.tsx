import React from "react";
import { render, screen, act, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeAll, afterAll } from "vitest";
import TemplatesPage from "../pages/TemplatesPage";
import { sortModelsForDisplay } from "../components/assetUtils";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { onePage } from "@/test/mocks/page";

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

vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => true,
  useCanManage: () => true,
}));

vi.mock("@/hooks/useConfirm", () => ({
  useConfirm: () => ({
    confirm: vi.fn(),
  }),
}));

vi.mock("@/modules/shared/hooks/useCategories", () => ({
  useCategories: () => ({ data: [] }),
  useAllCategories: () => ({ data: [] }),
}));

// The five seeded names that do not carry their brand — the card prepends
// it, so the reader looks for them under the brand. The list arrives in the
// backend's byte order over the raw name (L < M < T < U < i), which files
// every Apple under the letters the brand it hides sorts by.
const models = [
  { id: "m-1", name: "Logitech MX Keys S", brand: "Logitech" },
  { id: "m-2", name: "MacBook Pro 14 M3", brand: "Apple" },
  { id: "m-3", name: "ThinkPad T14s Gen 4", brand: "Lenovo" },
  { id: "m-4", name: "UniFi USW-Pro-48", brand: "Ubiquiti" },
  { id: "m-5", name: "iPad Air M2", brand: "Apple" },
].map((m) => ({
  image_url: null,
  description: null,
  category_id: null,
  category_name: null,
  equipment_meta: {},
  ...m,
}));

// The labels a reader scans, in the order the cards must stand.
const expectedOrder = [
  "Apple iPad Air M2",
  "Apple MacBook Pro 14 M3",
  "Lenovo ThinkPad T14s Gen 4",
  "Logitech MX Keys S",
  "Ubiquiti UniFi USW-Pro-48",
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

async function openModelsTab() {
  render(<TemplatesPage />, { wrapper: createWrapper() });
  await act(async () => {
    await new Promise((r) => setTimeout(r, 200));
  });
  switchTab(/Equipment Models/i);
  await screen.findByText("Ubiquiti UniFi USW-Pro-48", undefined, {
    timeout: 5000,
  });
}

function expectBefore(a: HTMLElement, b: HTMLElement) {
  const following =
    a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING;
  if (!following) {
    throw new Error(
      `expected "${a.textContent}" to stand before "${b.textContent}"`,
    );
  }
}

describe("the model catalogue reads in the order its cards read", () => {
  beforeEach(() => {
    server.resetHandlers();
    server.use(
      http.get("/api/v1/equipment/templates", () => HttpResponse.json([])),
      http.get("/api/v1/equipment/templates/placeholders", () =>
        HttpResponse.json([]),
      ),
      http.get("/api/v1/equipment/models", () =>
        HttpResponse.json(onePage(models)),
      ),
    );
  });

  it("files a model whose name hides the brand under the brand", async () => {
    await openModelsTab();

    for (let i = 0; i < expectedOrder.length - 1; i++) {
      expectBefore(
        screen.getByText(expectedOrder[i]),
        screen.getByText(expectedOrder[i + 1]),
      );
    }
  });
});

describe("the model catalogue can be searched", () => {
  beforeEach(() => {
    server.resetHandlers();
    server.use(
      http.get("/api/v1/equipment/templates", () => HttpResponse.json([])),
      http.get("/api/v1/equipment/templates/placeholders", () =>
        HttpResponse.json([]),
      ),
      http.get("/api/v1/equipment/models", () =>
        HttpResponse.json(onePage(models)),
      ),
    );
  });

  it("finds a model by the label it shows, not only the name it stores", async () => {
    await openModelsTab();

    // "apple" appears in no raw name of the five — only in the labels.
    await userEvent.type(screen.getByPlaceholderText(/search/i), "apple");

    expect(screen.getByText("Apple iPad Air M2")).toBeInTheDocument();
    expect(screen.getByText("Apple MacBook Pro 14 M3")).toBeInTheDocument();
    expect(screen.queryByText("Logitech MX Keys S")).toBeNull();
  });
});

describe("sortModelsForDisplay orders by the rules of the reader's language", () => {
  it("puts a Polish diacritic where the alphabet has it, not where the code point sits", () => {
    // Byte order compares ę (U+0119) against r from above 255 and files
    // "Brzechwa" first; the Polish alphabet keeps ę between e and f.
    const ordered = sortModelsForDisplay(
      [{ name: "Brzechwa" }, { name: "Bęben" }],
      "pl",
    );

    expect(ordered.map((m) => m.name)).toEqual(["Bęben", "Brzechwa"]);
  });

  it("reads a number in a name as a number", () => {
    const ordered = sortModelsForDisplay(
      [{ name: "Synology RS2423+" }, { name: "Synology RS820+" }],
      "en",
    );

    expect(ordered.map((m) => m.name)).toEqual([
      "Synology RS820+",
      "Synology RS2423+",
    ]);
  });
});
