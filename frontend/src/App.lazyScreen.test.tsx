/**
 * The first visit to a screen downloads it. For that moment the reader has
 * tapped and needs to see that the tap landed: the address had changed, but a
 * router update inside a React transition kept the old screen up, untouched,
 * for as long as the download took.
 *
 * The two sections below never finish loading, so what they pin is the state
 * in between: a loading sign in place of the old content, with the navigation
 * around it still standing rather than a full-page takeover.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { useAuthStore } from "@/store/authStore";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { tokenStore } from "@/lib/api/client";
import App from "./App";

vi.mock(
  "./modules/settings/pages/SettingsProfileSection",
  () => new Promise(() => {}),
);
vi.mock("./modules/settings/components/AppStore", () => new Promise(() => {}));

describe("a tap on a screen that has not been downloaded yet", () => {
  beforeEach(() => {
    tokenStore.set("test-token");
    const admin = {
      is_blocked: false,
      is_superuser: true,
      permissions: [],
      is_active: true,
      id: "1",
      full_name: "Test User",
      email: "test@example.com",
      preferred_language: "en" as const,
      role: "admin",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    useAuthStore.setState({ user: admin, isAuthenticated: true });
    server.use(
      // The boot's own session check: the module store's door is an admin's.
      http.get("*/api/v1/auth/me", () => HttpResponse.json(admin)),
      http.get("*/api/v1/modules/my", () =>
        HttpResponse.json(["core", "inventory"]),
      ),
      http.get("*/api/v1/about", () =>
        HttpResponse.json({ version: "1.0.0", source_code_url: null }),
      ),
    );
  });

  async function openAboutThenTap(href: string) {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ModulesProvider>
          <App initialEntries={["/settings/about"]} />
        </ModulesProvider>
      </QueryClientProvider>,
    );
    const about = await screen.findByText(/Copyright ©/);
    const link = await waitFor(() => {
      const found = document.querySelector<HTMLAnchorElement>(
        `a[href="${href}"]`,
      );
      expect(found).not.toBeNull();
      return found!;
    });
    await userEvent.setup().click(link);
    return about;
  }

  it("replaces a settings section with a loading sign, under the settings navigation", async () => {
    const about = await openAboutThenTap("/settings/profile");

    const main = screen.getByRole("main");
    expect(await within(main).findByRole("status")).toBeVisible();
    expect(about).not.toBeVisible();
    expect(screen.queryByTestId("app-loading")).toBeNull();
    expect(document.querySelector('a[href="/settings/about"]')).toBeVisible();
  });

  it("replaces a screen of the shell with a loading sign, under the shell", async () => {
    const about = await openAboutThenTap("/apps");

    const main = screen.getByRole("main");
    expect(await within(main).findByRole("status")).toBeVisible();
    expect(about).not.toBeVisible();
    expect(screen.queryByTestId("app-loading")).toBeNull();
    expect(screen.getByRole("banner")).toBeVisible();
  });
});
