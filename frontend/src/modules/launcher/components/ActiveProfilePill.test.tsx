import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { withLanguage } from "@/test/mocks/i18n";
import { useAuthStore } from "@/store/authStore";
import { ActiveProfilePill } from "./ActiveProfilePill";
import type { Organization, ProductProfile } from "@/types";
import { onePage } from "@/test/mocks/page";

const profiles: ProductProfile[] = [
  {
    id: "food_home",
    name: "Food & Home",
    description: "Track food inventory.",
    default_modules: ["items"],
    seed_profile: "food_home",
    icon: "ShoppingBasket",
  },
  // A profile the frontend cannot know at build time — the registry fields
  // are all it has to go on.
  {
    id: "vineyard_ops",
    name: "Vineyard Ops",
    description: "Barrels, blocks and harvest lots.",
    default_modules: ["items"],
    seed_profile: "vineyard_ops",
    icon: "Box",
  },
];

function makeOrg(activeProfileId: string | null): Organization {
  return {
    can_send_email: false,
    timezone: "UTC",
    currency: "PLN",
    id: "org-1",
    name: "Acme",
    created_at: new Date().toISOString(),
    created_by: null,
    settings: null,
    active_profile_id: activeProfileId,
    onboarding_completed: true,
  };
}

function setUpUser(role: string) {
  useAuthStore.setState({
    user: {
      is_blocked: false,
      permissions: [],
      is_active: true,
      id: "user-1",
      email: "u@example.com",
      full_name: "Test",
      role,
      is_superuser: false,
      preferred_language: "en",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
    isAuthenticated: true,
  });
}

function mockEndpoints(activeProfileId: string | null) {
  server.use(
    http.get("*/api/v1/profiles", () => HttpResponse.json(onePage(profiles))),
    http.get("*/api/v1/organizations/my", () =>
      HttpResponse.json(makeOrg(activeProfileId)),
    ),
  );
}

function renderPill() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ActiveProfilePill />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ActiveProfilePill", () => {
  it("renders the active profile name with a link to the My modules screen for admins", async () => {
    setUpUser("admin");
    mockEndpoints("food_home");
    renderPill();
    const link = await screen.findByRole("link", { name: /Food & Home/ });
    expect(link).toHaveAttribute("href", "/settings/my-modules");
  });

  it("renders nothing for non-admin users", async () => {
    setUpUser("member");
    mockEndpoints("food_home");
    const { container } = renderPill();
    // Give the queries time to settle — nothing should ever appear.
    await waitFor(() => {
      expect(container).toBeEmptyDOMElement();
    });
  });

  it("renders nothing when the org has no active profile", async () => {
    setUpUser("admin");
    mockEndpoints(null);
    const { container } = renderPill();
    await waitFor(() => {
      expect(container).toBeEmptyDOMElement();
    });
  });

  it("names the active profile in the user's language", async () => {
    setUpUser("admin");
    mockEndpoints("food_home");
    await withLanguage("pl", async () => {
      const { unmount } = renderPill();
      const link = await screen.findByRole("link", {
        name: /Dom i jedzenie/,
      });
      expect(link).toBeInTheDocument();
      expect(screen.queryByText("Food & Home")).not.toBeInTheDocument();
      unmount();
    });
  });

  it("falls back to the registry name for a profile outside the catalog", async () => {
    setUpUser("admin");
    mockEndpoints("vineyard_ops");
    await withLanguage("pl", async () => {
      const { unmount } = renderPill();
      expect(
        await screen.findByRole("link", { name: /Vineyard Ops/ }),
      ).toBeInTheDocument();
      unmount();
    });
  });
});
