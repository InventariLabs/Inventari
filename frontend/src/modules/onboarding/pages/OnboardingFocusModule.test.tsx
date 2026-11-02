import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { moduleRegistry } from "@/lib/moduleRegistry";
import type { FrontendModule } from "@/lib/moduleRegistry";
import OnboardingPage from "./OnboardingPage";
import { onePage } from "@/test/mocks/page";

vi.mock("@/lib/moduleRegistry/moduleLoaders", () => ({
  registerModules: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

const profiles = [
  {
    id: "food_home",
    name: "Food & Home",
    description: "d",
    default_modules: [],
  },
  { id: "clean_core", name: "Custom", description: "d", default_modules: [] },
];

const catalogue = ["recipes", "equipment"].map((name) => ({
  name,
  display_name: name === "recipes" ? "Recipes" : "Equipment",
  description: `${name} module`,
  icon: "box",
  is_always_on: false,
  requires: [],
}));

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/onboarding"]}>
        <Routes>
          <Route path="/onboarding" element={<OnboardingPage />} />
          <Route path="/" element={<div>LAUNCHER</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function useHandlers(onSetup?: (body: unknown) => void) {
  server.use(
    http.get("*/api/v1/profiles", () => HttpResponse.json(onePage(profiles))),
    http.get("*/api/v1/modules/available", () =>
      HttpResponse.json(onePage(catalogue)),
    ),
    http.get("*/api/v1/organizations/my", () =>
      HttpResponse.json({ id: "org-1", onboarding_completed: false }),
    ),
    http.post("*/api/v1/onboarding/setup", async ({ request }) => {
      onSetup?.(await request.json());
      return HttpResponse.json({ id: "org-1", onboarding_completed: true });
    }),
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("OnboardingPage — the one-module choice", () => {
  it("lists only standalone modules and sends the choice with the base profile", async () => {
    const bodies: unknown[] = [];
    useHandlers((b) => bodies.push(b));
    vi.spyOn(moduleRegistry, "getStandaloneModules").mockImplementation(() => [
      { name: "recipes" } as FrontendModule,
    ]);
    vi.spyOn(moduleRegistry, "getModule").mockImplementation(
      () => ({ routes: [{ path: "/recipes" }] }) as unknown as FrontendModule,
    );

    const replace = vi.fn();
    vi.stubGlobal("location", { ...window.location, replace });

    renderPage();
    await userEvent.click(
      await screen.findByRole("button", { name: /just one module/i }),
    );
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));

    expect(await screen.findByLabelText(/recipes/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/equipment/i)).not.toBeInTheDocument();
    const confirm = screen.getByRole("button", { name: /get started/i });
    expect(confirm).toBeDisabled();

    await userEvent.click(screen.getByLabelText(/recipes/i));
    await userEvent.click(confirm);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/recipes"));
    expect(bodies[0]).toMatchObject({
      profile_id: "clean_core",
      focus_module: "recipes",
    });
  });

  it("says the modules could not be loaded instead of listing none", async () => {
    useHandlers();
    server.use(
      http.get(
        "*/api/v1/modules/available",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    renderPage();
    await userEvent.click(
      await screen.findByRole("button", { name: /just one module/i }),
    );
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /try again|retry/i }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
  });

  it("lists the modules once the reader retries a failed load", async () => {
    useHandlers();
    let calls = 0;
    server.use(
      http.get("*/api/v1/modules/available", () => {
        calls += 1;
        return calls === 1
          ? new HttpResponse(null, { status: 500 })
          : HttpResponse.json(onePage(catalogue));
      }),
    );
    vi.spyOn(moduleRegistry, "getStandaloneModules").mockImplementation(() => [
      { name: "recipes" } as FrontendModule,
    ]);

    renderPage();
    await userEvent.click(
      await screen.findByRole("button", { name: /just one module/i }),
    );
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    await userEvent.click(
      await screen.findByRole("button", { name: /try again|retry/i }),
    );

    expect(await screen.findByLabelText(/recipes/i)).toBeInTheDocument();
    expect(calls).toBe(2);
  });
});
