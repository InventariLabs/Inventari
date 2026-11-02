import { render, waitFor, screen } from "@testing-library/react";
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { withLanguage } from "@/test/mocks/i18n";
import App from "./App";

/**
 * The document's language says what the screen in front of the reader is
 * written in, on the routes a visitor reaches before signing in.
 *
 * `<html lang="en">` in index.html is right for everything that reads the
 * document before React mounts and wrong the moment React draws a Polish form.
 * Only the signed-in shell ever corrected it, so /login and /register shipped
 * English phonetics over Polish text and the browser offered to translate the
 * page it was already showing. A screen reader decides how to pronounce the
 * first word on the page from this attribute alone.
 */
describe("the document language on a route reached before signing in", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    // What index.html ships: a Polish screen starting from an English document.
    document.documentElement.lang = "en";
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    server.use(
      http.get("/api/v1/auth/init-status", () =>
        HttpResponse.json({ is_initialized: true }),
      ),
    );
  });

  afterEach(() => {
    document.documentElement.lang = "en";
  });

  it("declares the language the login screen renders in", async () => {
    await withLanguage("pl", async () => {
      render(
        <QueryClientProvider client={queryClient}>
          <ModulesProvider>
            <App initialEntries={["/login"]} />
          </ModulesProvider>
        </QueryClientProvider>,
      );

      await waitFor(() => {
        expect(document.documentElement.lang).toBe("pl");
      });

      // The screen and the attribute have to be the same language, or the
      // assertion above would pass on a document that says nothing about
      // what is on it.
      expect(
        await screen.findByText("Zaloguj się na swoje konto"),
      ).toBeInTheDocument();
    });
  });
});
