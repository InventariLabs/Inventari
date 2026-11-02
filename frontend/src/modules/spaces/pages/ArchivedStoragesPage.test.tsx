import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useCallback, useState, type ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";

// jsdom's window.location is a static mock here, so navigation is asserted
// through the navigate spy instead of the address bar.
const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => mockNavigate };
});
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import ArchivedStoragesPage from "./ArchivedStoragesPage";
import { useAuthStore } from "@/store/authStore";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

type HeaderData = { actions?: ReactNode };

function HeaderHost({ children }: { children: ReactNode }) {
  const [header, setHeader] = useState<HeaderData>({});
  const stableSetHeader = useCallback((data: HeaderData) => {
    setHeader(data);
  }, []);
  return (
    <PageHeaderContext.Provider
      value={{ data: header, setHeader: stableSetHeader }}
    >
      {children}
    </PageHeaderContext.Provider>
  );
}

/**
 * Archiving is the way out for a location that may not be deleted, so the
 * door has to open both ways: before this screen the only way back was an
 * UPDATE against the database.
 */
describe("ArchivedStoragesPage", () => {
  let queryClient: QueryClient;
  let restored: string[];

  const renderPage = () =>
    render(
      <MemoryRouter>
        <QueryClientProvider client={queryClient}>
          <HeaderHost>
            <ArchivedStoragesPage />
          </HeaderHost>
        </QueryClientProvider>
      </MemoryRouter>,
    );

  /** Restoring a location is `locations:write` on the API, so the screen only
   *  offers it to an account that holds the key. */
  function signIn(permissions: string[]) {
    useAuthStore.setState({
      user: {
        is_blocked: false,
        is_superuser: false,
        is_active: true,
        id: "u-1",
        full_name: "Test User",
        email: "test@example.com",
        preferred_language: "en",
        role: "user",
        permissions,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      isAuthenticated: true,
    });
  }

  beforeEach(() => {
    signIn(["locations:write"]);
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    restored = [];
    server.use(
      http.get("/api/v1/locations/archived", () =>
        HttpResponse.json(
          onePage([{ id: "s-1", name: "Fridge", settings: {} }]),
        ),
      ),
      http.post("/api/v1/locations/:id/unarchive", ({ params }) => {
        restored.push(String(params.id));
        return HttpResponse.json({ id: params.id, name: "Fridge" });
      }),
    );
  });

  it("lists what every other screen hides", async () => {
    renderPage();

    expect(await screen.findByText("Fridge")).toBeInTheDocument();
  });

  it("tells two archived locations that share a name apart by their path", async () => {
    // A location's identity is its path, not its name: "Shelf 1" under Server
    // Room and "Shelf 1" under IT Workshop were two identical rows carrying
    // two identical Restore buttons — the restore of one was a guess.
    server.use(
      http.get("/api/v1/locations/archived", () =>
        HttpResponse.json(
          onePage([
            {
              id: "s-1",
              name: "Shelf 1",
              settings: {},
              full_path: "Server Room → Shelf 1",
              archived_at: "2026-09-01T10:00:00Z",
            },
            {
              id: "s-2",
              name: "Shelf 1",
              settings: {},
              full_path: "IT Workshop → Shelf 1",
              archived_at: "2026-08-15T10:00:00Z",
            },
          ]),
        ),
      ),
    );

    renderPage();

    expect(
      await screen.findByText("Server Room → Shelf 1"),
    ).toBeInTheDocument();
    expect(screen.getByText("IT Workshop → Shelf 1")).toBeInTheDocument();
    expect(screen.getAllByTestId("archived-storage-row")).toHaveLength(2);
  });

  it("shows when each location left the lists", async () => {
    // The moment lives in the organization journal (SOFT_DELETE storage), and
    // the row used to show the name alone — nothing said which of two same-
    // named rows was archived when.
    server.use(
      http.get("/api/v1/locations/archived", () =>
        HttpResponse.json(
          onePage([
            {
              id: "s-1",
              name: "Fridge",
              settings: {},
              full_path: "Cold Storage → Fridge",
              archived_at: "2026-07-01T00:00:00Z",
            },
          ]),
        ),
      ),
    );

    renderPage();

    expect(await screen.findByText("Fridge")).toBeInTheDocument();
    // formatDate renders the year in every supported locale — enough to tell
    // a rendered moment from the em dash a missing one shows.
    expect(screen.getByText(/2026/)).toBeInTheDocument();
  });

  it("restores a location on request", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Fridge");

    await user.click(screen.getByRole("button", { name: /restore/i }));

    await waitFor(() => expect(restored).toEqual(["s-1"]));
  });

  it("leads back to the active list, which is the only way back now", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Fridge");

    expect(screen.getByRole("tab", { name: "Archived" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    await user.click(screen.getByRole("tab", { name: "Active" }));

    expect(mockNavigate).toHaveBeenCalledWith("/inventory/locations");
  });

  it("does not offer the way back to an account that may not take it", async () => {
    signIn([]);
    renderPage();

    expect(await screen.findByText("Fridge")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /restore/i })).toBeNull();
  });

  it("says so plainly when nothing is archived", async () => {
    server.use(
      http.get("/api/v1/locations/archived", () =>
        HttpResponse.json(onePage([])),
      ),
    );

    renderPage();

    expect(await screen.findByText("Nothing archived")).toBeInTheDocument();
  });

  it("asks for the same module scope the active tab applies", async () => {
    // The two tabs describe one population: with the module-data policy off,
    // the archive request carries the same exclusion the active list sends.
    const seen: string[] = [];
    server.events.on("request:start", ({ request }) => {
      if (request.url.includes("/locations/archived")) seen.push(request.url);
    });

    renderPage();

    await screen.findByText("Fridge");
    expect(seen.some((u) => u.includes("exclude_module_contexts=true"))).toBe(
      true,
    );
  });

  it("drops the scope when the organization shows module data", async () => {
    server.use(
      http.get("/api/v1/organizations/my", () =>
        HttpResponse.json({
          id: "1",
          name: "Org",
          settings: { show_module_data: true },
        }),
      ),
    );
    const seen: string[] = [];
    server.events.on("request:start", ({ request }) => {
      if (request.url.includes("/locations/archived")) seen.push(request.url);
    });

    renderPage();

    await screen.findByText("Fridge");
    // The org answer arrives after the first render, so an early scoped
    // request precedes the converged one — the same warm-up the active tab
    // runs. What matters is where the list settles.
    await waitFor(() =>
      expect(seen.some((u) => !u.includes("exclude_module_contexts"))).toBe(
        true,
      ),
    );
  });
});
