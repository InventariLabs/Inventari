/**
 * Refusals in the reader's language, on the public page: the attestation
 * link pins a language with ?lang=, and the API's own refusals surface here
 * verbatim through useAppMutation (the API message wins over the translated
 * fallback). The public calls must therefore carry the chosen language the
 * way the authenticated client does — an expired link may not read in the
 * deployment's default language.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@/test/utils";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import i18next from "i18next";
import AttestationPublicPage from "@/modules/equipment/pages/AttestationPublicPage";

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useParams: () => ({ token: "tok-1" }),
    useSearchParams: () => [new URLSearchParams("lang=pl"), vi.fn()],
  };
});

const pendingResponse = {
  id: "resp-1",
  campaign_id: "camp-1",
  assignment_id: "asg-1",
  assignee_email: "anna@example.com",
  assignee_name: "Anna Kowalska",
  item_name: "Laptop A",
  serial_number: "SN-A",
  items: [
    {
      id: "item-1",
      response_id: "resp-1",
      assignment_id: "asg-1",
      item_id: "it-1",
      item_name: "Laptop A",
      serial_number: "SN-A",
      status: "PENDING" as const,
      dispute_type: null,
      dispute_reason: null,
    },
  ],
  status: "PENDING",
  responded_at: null,
  dispute_reason: null,
  dispute_type: null,
  email_sent_at: null,
  created_at: "2026-08-01T00:00:00Z",
};

describe("the public attestation call speaks the pinned language", () => {
  it("carries the app's language on the unauthenticated fetch", async () => {
    // The page sets the language from ?lang= itself; setting it here too
    // keeps the assertion independent of effect-vs-fetch ordering.
    await i18next.changeLanguage("pl");
    let seenLanguage: string | null = null;
    server.use(
      http.get("/public/attestation/tok-1", ({ request }) => {
        seenLanguage = request.headers.get("Accept-Language");
        return HttpResponse.json(pendingResponse);
      }),
    );
    window.history.pushState({}, "", "/public/attestation/tok-1?lang=pl");

    render(<AttestationPublicPage />);

    await waitFor(() => {
      expect(screen.getByText("Laptop A")).toBeInTheDocument();
    });
    expect(seenLanguage).toBe("pl");
    await i18next.changeLanguage("en");
  });
});
