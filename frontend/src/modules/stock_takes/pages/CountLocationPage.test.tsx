import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import CountLocationPage from "./CountLocationPage";
import { useAuthStore } from "@/store/authStore";
import { server } from "@/test/mocks/server";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import * as modulesCtx from "@/contexts/ModulesContext";
import { serveLocations } from "@/test/serveLocations";
import { onePage } from "@/test/mocks/page";

const camera = vi.hoisted(() => ({
  onCode: (_code: string) => {},
}));

// The page draws its camera panel closed; what matters here is the code the
// camera would hand over, which takes the same road as a typed one.
vi.mock("@/hooks/useScanCamera", () => ({
  useTorchAvailable: () => false,
  useScanCamera: (options: { onCodeScanned: (code: string) => void }) => {
    camera.onCode = options.onCodeScanned;
    return {
      scannerError: null,
      isCameraActive: false,
      setIsCameraActive: vi.fn(),
      restartCamera: vi.fn(),
      isTorchOn: false,
      toggleTorch: vi.fn(),
    };
  },
}));

const DAY = 24 * 60 * 60 * 1000;
const daysAgo = (days: number) =>
  new Date(Date.now() - days * DAY - 60_000).toISOString();

const storage = (id: string, name: string) => ({
  id,
  name,
  parent_id: null,
});

let requests: URLSearchParams[];

let created: Record<string, unknown> | null;

function renderPage(path = "/inventory/stock-takes/count") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const header = { data: { title: "", actions: null }, setHeader: vi.fn() };
  const Shell = ({ children }: { children: ReactNode }) => (
    <PageHeaderContext.Provider value={header}>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[path]}>{children}</MemoryRouter>
      </QueryClientProvider>
    </PageHeaderContext.Provider>
  );
  return render(
    <Shell>
      <Routes>
        <Route
          path="/inventory/stock-takes/count"
          element={<CountLocationPage />}
        />
        <Route
          path="/inventory/stock-takes/:id/counting"
          element={<p>counting screen</p>}
        />
      </Routes>
    </Shell>,
  );
}

beforeEach(() => {
  created = null;
  vi.spyOn(modulesCtx, "useModules").mockReturnValue({
    enabledModules: ["stock_takes"],
    isModuleEnabled: (name: string) => name === "stock_takes",
    isLoading: false,
    refreshModules: vi.fn(),
    focusModule: null,
    hiddenModules: [],
  });
  requests = serveLocations([
    storage("a", "Shelf A"),
    storage("b", "Shelf B"),
    storage("c", "Cold room"),
  ]);
  server.use(
    http.get("/api/v1/stock-takes/locations", () =>
      HttpResponse.json(
        onePage([
          { location_id: "a", last_counted_at: daysAgo(3) },
          { location_id: "b", last_counted_at: daysAgo(62) },
          {
            location_id: "c",
            last_counted_at: null,
            stock_take_id: "open-1",
          },
        ]),
      ),
    ),
    http.post("/api/v1/stock-takes", async ({ request }) => {
      created = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json({ id: "new-1", ...created }, { status: 201 });
    }),
  );
  useAuthStore.setState({
    user: {
      is_blocked: false,
      is_superuser: false,
      is_active: true,
      id: "1",
      full_name: "Counter",
      email: "counter@example.com",
      preferred_language: "en",
      role: "user",
      permissions: ["stock_takes:read", "stock_takes:write"],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
    isAuthenticated: true,
  });
});

describe("CountLocationPage", () => {
  it("lists the places with when they were counted, the longest ago first", async () => {
    renderPage();

    const list = await screen.findByRole("list");
    const rows = within(list).getAllByRole("button");
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringContaining("Cold room"),
      expect.stringContaining("Shelf B"),
      expect.stringContaining("Shelf A"),
    ]);
    expect(rows[0]).toHaveTextContent("Being counted");
    expect(rows[1]).toHaveTextContent("Last counted 62 days ago");
    expect(rows[2]).toHaveTextContent("Last counted 3 days ago");
  });

  it("starts a blind count of the chosen place and opens its counting", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Shelf B/ }));
    await user.click(screen.getByRole("checkbox", { name: /Blind count/ }));
    await user.click(screen.getByRole("button", { name: "Count Shelf B" }));

    expect(await screen.findByText("counting screen")).toBeInTheDocument();
    expect(created).toMatchObject({
      location_id: "b",
      blind_mode: true,
    });
    expect(String(created?.name)).toContain("Shelf B");
  });

  it("opens with the place a due task named, and resumes a count under way", async () => {
    const user = userEvent.setup();
    renderPage("/inventory/stock-takes/count?location=a");

    expect(
      await screen.findByRole("button", { name: "Count Shelf A" }),
    ).toBeEnabled();

    await user.click(screen.getByRole("button", { name: /Cold room/ }));
    expect(await screen.findByText("counting screen")).toBeInTheDocument();
    expect(created).toBeNull();
  });

  it("asks for a place before it can start", async () => {
    renderPage();

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Choose a location to count" }),
      ).toBeDisabled(),
    );
  });

  it("finds a place among two thousand by asking the server, not by loading them", async () => {
    const user = userEvent.setup();
    requests = serveLocations(
      Array.from({ length: 2000 }, (_, i) => storage(`s${i}`, `Rack ${i}`)),
    );
    renderPage();

    await screen.findByRole("list");
    expect(
      screen.getAllByRole("button", { name: /Rack/ }).length,
    ).toBeLessThanOrEqual(30);

    await user.type(
      screen.getByRole("textbox", { name: "Find a location" }),
      "Rack 1999",
    );
    await user.click(await screen.findByRole("button", { name: /Rack 1999/ }));
    expect(
      screen.getByRole("button", { name: "Count Rack 1999" }),
    ).toBeEnabled();

    // Every read was a page: none asked for the catalogue.
    expect(requests.every((r) => Number(r.get("limit")) <= 30)).toBe(true);
    expect(requests.some((r) => r.get("q") === "Rack 1999")).toBe(true);
  });
});

/**
 * The ways into a count other than picking from the list, and the ways a
 * start can fail.
 */
describe("CountLocationPage — scanning and failing", () => {
  const serveLocationScan = (
    code: string,
    locationId: string,
    name: string,
  ) => {
    const asked: string[] = [];
    server.use(
      http.get("/api/v1/labels/scan/:code", ({ params }) => {
        asked.push(String(params.code));
        return HttpResponse.json({
          status: "storage_context",
          label_code: code,
          action: "set_storage_context",
          location: { id: locationId, name, icon: "box" },
        });
      }),
    );
    return asked;
  };

  it("chooses the place whose label was typed into the scan field", async () => {
    const user = userEvent.setup();
    const asked = serveLocationScan("LOC-B", "b", "Shelf B");
    renderPage();
    await screen.findByRole("list");

    await user.type(screen.getByLabelText("Location label"), "LOC-B{Enter}");

    expect(
      await screen.findByRole("button", { name: "Count Shelf B" }),
    ).toBeEnabled();
    expect(asked).toEqual(["LOC-B"]);
    // The field is emptied for the next label.
    expect(screen.getByLabelText("Location label")).toHaveValue("");
  });

  it("does not look anything up for an empty scan field", async () => {
    const user = userEvent.setup();
    const asked = serveLocationScan("x", "b", "Shelf B");
    renderPage();
    await screen.findByRole("list");

    await user.type(screen.getByLabelText("Location label"), "   {Enter}");

    expect(asked).toEqual([]);
    expect(
      screen.getByRole("button", { name: "Choose a location to count" }),
    ).toBeDisabled();
  });

  it("chooses the place the camera read, exactly like a typed label", async () => {
    const asked = serveLocationScan("LOC-A", "a", "Shelf A");
    renderPage();
    await screen.findByRole("list");

    act(() => camera.onCode("LOC-A"));

    expect(
      await screen.findByRole("button", { name: "Count Shelf A" }),
    ).toBeEnabled();
    expect(asked).toEqual(["LOC-A"]);
  });

  it("says why the count did not start and lets the reader try again", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/v1/stock-takes", () =>
        HttpResponse.json(
          { detail: "Someone is already counting this location" },
          { status: 409 },
        ),
      ),
    );
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Shelf A/ }));
    await user.click(screen.getByRole("button", { name: "Count Shelf A" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Someone is already counting this location",
    );
    expect(screen.queryByText("counting screen")).toBeNull();
    expect(screen.getByRole("button", { name: "Count Shelf A" })).toBeEnabled();
  });

  it("asks the server again when the list could not be read and the reader retries", async () => {
    const user = userEvent.setup();
    let failing = true;
    server.use(
      http.get("/api/v1/stock-takes/locations", () =>
        failing
          ? new HttpResponse(null, { status: 500 })
          : HttpResponse.json(onePage([])),
      ),
    );
    renderPage();

    const retry = await screen.findByRole("button", { name: /try again/i });
    failing = false;
    await user.click(retry);

    expect(
      await screen.findByRole("button", { name: /Shelf A/ }),
    ).toBeInTheDocument();
  });
});
