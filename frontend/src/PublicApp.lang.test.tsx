import { render, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { withLanguage } from "@/test/mocks/i18n";
import PublicApp from "./PublicApp";

/**
 * The attestation link is the one page served without `App`, and it speaks
 * the reader's language (`?lang=`, the browser's) from index.html's
 * `lang="en"`: the document has to say what is written on it.
 */
function renderPublic() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <PublicApp initialEntries={["/public/attestation/tok-1"]} />
    </QueryClientProvider>,
  );
}

describe("the document language and title on the public tree", () => {
  beforeEach(() => {
    document.documentElement.lang = "en";
    document.title = "Inventari";
    server.use(
      http.get("/public/attestation/tok-1", () =>
        HttpResponse.json({ detail: "gone" }, { status: 404 }),
      ),
    );
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    document.documentElement.lang = "en";
    vi.restoreAllMocks();
  });

  it("declares the language the attestation page renders in", async () => {
    await withLanguage("pl", async () => {
      renderPublic();
      await waitFor(() => {
        expect(document.documentElement.lang).toBe("pl");
      });
    });
  });

  it("names the tab after the page, in that language", async () => {
    await withLanguage("pl", async () => {
      renderPublic();
      await waitFor(() => {
        expect(document.title).toBe("Atestacja zasobu · Inventari");
      });
    });
  });
});
