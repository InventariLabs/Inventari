import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import i18next from "i18next";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { LanguageSelector } from "@/components/LanguageSelector";
import { UserMenu } from "@/components/shell/UserMenu";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { tokenStore } from "@/lib/api/client";
import { useAuthStore } from "@/store/authStore";
import { server } from "@/test/mocks/server";
import type { User } from "@/types";
import SettingsProfileSection from "./SettingsProfileSection";

const ANNA: User = {
  id: "1",
  email: "anna@example.com",
  full_name: "Anna Nowak",
  role: "manager",
  is_active: true,
  is_superuser: false,
  is_blocked: false,
  permissions: ["items:read"],
  preferred_language: "en",
};

/** The shell's two places that show the signed-in person and the language. */
function TopBar() {
  const user = useAuthStore((state) => state.user);
  return (
    <>
      <UserMenu user={user} onLogout={() => {}} />
      <LanguageSelector />
    </>
  );
}

function renderProfile() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MemoryRouter>
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider client={queryClient}>
          <TopBar />
          <SettingsProfileSection />
        </QueryClientProvider>
      </PageHeaderContext.Provider>
    </MemoryRouter>,
  );
}

function servePatch(status: number, body: object) {
  const sent: unknown[] = [];
  server.use(
    http.patch("*/auth/me", async ({ request }) => {
      sent.push(await request.json());
      return HttpResponse.json(body, { status });
    }),
  );
  return sent;
}

function serveDemo(isDemo: boolean) {
  server.use(
    http.get("*/auth/init-status", () =>
      HttpResponse.json({
        is_initialized: true,
        is_demo: isDemo,
        demo_inbox_url: null,
      }),
    ),
  );
}

async function fillPassword(current: string, next: string, confirm: string) {
  const user = userEvent.setup();
  // The form appears once the installation has said it is not the demo.
  const currentField = await screen.findByLabelText(/Current password/);
  if (current) await user.type(currentField, current);
  if (next) await user.type(screen.getByLabelText(/New password/), next);
  if (confirm)
    await user.type(screen.getByLabelText(/Confirm password/), confirm);
  await user.click(screen.getByRole("button", { name: "Change password" }));
}

describe("SettingsProfileSection", () => {
  beforeEach(() => {
    act(() => {
      useAuthStore.setState({
        user: ANNA,
        isAuthenticated: true,
        isLoading: false,
        authUnavailable: false,
        signOutReason: null,
      });
    });
    tokenStore.set("a_session_token");
    serveDemo(false);
  });

  afterEach(async () => {
    await act(() => i18next.changeLanguage("en"));
  });

  describe("the name", () => {
    it("shows the new name in the user menu as soon as it is saved", async () => {
      const sent = servePatch(200, { ...ANNA, full_name: "Anna Kowalska" });
      const user = userEvent.setup();
      renderProfile();

      const field = screen.getByLabelText(/Full name/);
      await user.clear(field);
      await user.type(field, "  Anna Kowalska ");
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(
        await screen.findByRole("button", { name: "Anna Kowalska" }),
      ).toBeInTheDocument();
      expect(sent).toEqual([{ full_name: "Anna Kowalska" }]);
      expect(useAuthStore.getState().user?.permissions).toEqual(["items:read"]);
    });

    it("offers nothing to save until the name changes, and refuses an empty one", async () => {
      const user = userEvent.setup();
      renderProfile();

      const save = screen.getByRole("button", { name: "Save" });
      expect(save).toBeDisabled();

      await user.clear(screen.getByLabelText(/Full name/));

      expect(screen.getByText("Enter your name.")).toBeInTheDocument();
      expect(save).toBeDisabled();
    });

    it("names the address the person signs in with, which this screen does not change", () => {
      renderProfile();

      expect(
        screen.getByText(/You sign in as anna@example\.com/),
      ).toBeInTheDocument();
      expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument();
    });
  });

  describe("the language", () => {
    it("is the same setting as the top bar's selector, in both directions", async () => {
      const saved: unknown[] = [];
      server.use(
        http.post("*/auth/me/language", async ({ request }) => {
          saved.push(await request.json());
          return HttpResponse.json(ANNA);
        }),
      );
      const user = userEvent.setup();
      renderProfile();

      await user.selectOptions(screen.getByRole("combobox"), "pl");

      // The whole screen now speaks Polish, the top bar included.
      expect(
        await screen.findByRole("button", { name: "PL, Język: Polski" }),
      ).toBeInTheDocument();
      expect(screen.getByLabelText("Język interfejsu")).toHaveValue("pl");

      await user.click(
        screen.getByRole("button", { name: "PL, Język: Polski" }),
      );
      await user.click(screen.getByRole("button", { name: "English" }));

      await waitFor(() =>
        expect(screen.getByLabelText("Interface language")).toHaveValue("en"),
      );
      expect(saved).toEqual([{ language: "pl" }, { language: "en" }]);
    });
  });

  describe("the password", () => {
    it("says the current password is wrong at the field it is about, and keeps the session", async () => {
      servePatch(400, {
        detail: {
          code: "VALIDATION_ERROR",
          message: "Current password is incorrect",
          field: "current_password",
        },
      });
      renderProfile();

      await fillPassword("NotMine123", "NewPass456", "NewPass456");

      expect(
        await screen.findByText("The current password is not correct."),
      ).toBeInTheDocument();
      expect(useAuthStore.getState().isAuthenticated).toBe(true);
    });

    it("takes a refusal off the field once the person types a new value", async () => {
      servePatch(200, ANNA);
      const user = userEvent.setup();
      renderProfile();

      await fillPassword("OldPass123", "Ab1", "Ab1");
      expect(
        screen.getByText("Password must be at least 8 characters."),
      ).toBeInTheDocument();

      await user.type(screen.getByLabelText(/New password/), "cdefgh");

      expect(
        screen.queryByText("Password must be at least 8 characters."),
      ).not.toBeInTheDocument();
    });

    it("refuses a new password that is too short before asking the server", async () => {
      const sent = servePatch(200, ANNA);
      renderProfile();

      await fillPassword("OldPass123", "Ab1", "Ab1");

      expect(
        screen.getByText("Password must be at least 8 characters."),
      ).toBeInTheDocument();
      expect(sent).toEqual([]);
    });

    it("refuses a confirmation that does not match before asking the server", async () => {
      const sent = servePatch(200, ANNA);
      renderProfile();

      await fillPassword("OldPass123", "NewPass456", "NewPass457");

      expect(screen.getByText("Passwords do not match.")).toBeInTheDocument();
      expect(sent).toEqual([]);
    });

    it("asks for the current password before anything is sent", async () => {
      const sent = servePatch(200, ANNA);
      renderProfile();

      await fillPassword("", "NewPass456", "NewPass456");

      expect(
        screen.getByText("Enter your current password."),
      ).toBeInTheDocument();
      expect(sent).toEqual([]);
    });

    it("sends the current password with the new one and ends the session with the reason", async () => {
      const sent = servePatch(200, ANNA);
      renderProfile();

      await fillPassword("OldPass123", "NewPass456", "NewPass456");

      await waitFor(() =>
        expect(useAuthStore.getState().signOutReason).toBe("passwordChanged"),
      );
      expect(sent).toEqual([
        { current_password: "OldPass123", password: "NewPass456" },
      ]);
      expect(useAuthStore.getState().isAuthenticated).toBe(false);
    });

    it("on the public demo shows the password as locked, with the reason, and offers no form", async () => {
      serveDemo(true);
      renderProfile();

      expect(
        await screen.findByText(
          /This is the public demo, so the password cannot be changed here/,
        ),
      ).toBeInTheDocument();
      expect(
        screen.queryByLabelText(/Current password/),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Change password" }),
      ).not.toBeInTheDocument();
    });
  });
});
