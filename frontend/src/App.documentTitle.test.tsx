import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { withLanguage } from "@/test/mocks/i18n";
import App from "./App";

/**
 * The tab, the bookmark and the history entry name the page — in the language
 * on screen — and follow it from one route to the next. A screen reader
 * announces the document title on every navigation; it used to be
 * `Inventari` everywhere.
 */
describe("the document title on the routes reached before signing in", () => {
  beforeEach(() => {
    document.title = "Inventari";
    server.use(
      http.get("/api/v1/auth/init-status", () =>
        HttpResponse.json({ is_initialized: true }),
      ),
    );
  });

  afterEach(() => {
    document.title = "Inventari";
  });

  function renderApp(path: string) {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <ModulesProvider>
          <App initialEntries={[path]} />
        </ModulesProvider>
      </QueryClientProvider>,
    );
  }

  it("names the sign-in screen and then the one navigated to", async () => {
    renderApp("/login");
    await waitFor(() => {
      expect(document.title).toBe("Sign in to your account · Inventari");
    });

    await userEvent.click(await screen.findByRole("link", { name: /forgot/i }));
    await waitFor(() => {
      expect(document.title).toBe("Reset your password · Inventari");
    });
  });

  it("speaks the language on screen", async () => {
    await withLanguage("pl", async () => {
      renderApp("/login");
      await waitFor(() => {
        expect(document.title).toBe("Zaloguj się na swoje konto · Inventari");
      });
    });
  });
});
