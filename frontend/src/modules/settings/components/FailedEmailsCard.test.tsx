import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { act } from "react";
import i18n from "i18next";
import FailedEmailsCard from "./FailedEmailsCard";
import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";

function renderCard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <FailedEmailsCard />
    </QueryClientProvider>,
  );
}

const FAILURE = {
  id: "job-1",
  to_email: "anna@example.com",
  subject: "You have been invited",
  attempts: 5,
  max_attempts: 5,
  last_error: "[Errno 111] Connection refused",
  created_at: new Date("2026-09-20T10:00:00Z").toISOString(),
};

describe("FailedEmailsCard", () => {
  it("names the recipient, the message and what the relay said", async () => {
    // "It failed" leaves an administrator guessing between a wrong password,
    // a closed port and a host that never answered.
    server.use(
      http.get("*/organizations/my/failed-emails", () =>
        HttpResponse.json(onePage([FAILURE])),
      ),
    );

    renderCard();

    const row = await screen.findByTestId("failed-email-row");
    expect(within(row).getByText("anna@example.com")).toBeInTheDocument();
    expect(within(row).getByText("You have been invited")).toBeInTheDocument();
    expect(
      within(row).getByText(/Errno 111.*Connection refused/),
    ).toBeInTheDocument();
  });

  it("says nothing was lost rather than showing an empty list", async () => {
    server.use(
      http.get("*/organizations/my/failed-emails", () =>
        HttpResponse.json(onePage([])),
      ),
    );

    renderCard();

    expect(await screen.findByText("Nothing was lost")).toBeInTheDocument();
    expect(screen.queryByTestId("failed-email-row")).not.toBeInTheDocument();
  });

  it("does not call an empty queue lossless when no mail server is configured", async () => {
    // The badge above says "Not configured": the queue is empty because
    // nothing is ever queued, not because everything arrived.
    server.use(
      http.get("*/organizations/my/failed-emails", () =>
        HttpResponse.json(onePage([])),
      ),
      http.get("*/organizations/my", () =>
        HttpResponse.json({ id: "org-1", name: "Acme", can_send_email: false }),
      ),
    );

    renderCard();

    expect(
      await screen.findByText("Nothing has been sent"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Nothing was lost")).not.toBeInTheDocument();
  });

  it("offers a retry when the read itself fails", async () => {
    // A card that renders "nothing was lost" over a 500 is worse than one
    // that says it could not look.
    server.use(
      http.get("*/organizations/my/failed-emails", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    renderCard();

    expect(
      await screen.findByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Nothing was lost")).not.toBeInTheDocument();
  });

  it("translates the reasons the mail queue writes itself", async () => {
    // These sentences come from the backend in English whatever the reader's
    // language is; they are the part an administrator acts on.
    server.use(
      http.get("*/organizations/my/failed-emails", () =>
        HttpResponse.json(
          onePage([{ ...FAILURE, last_error: "SMTP is not configured" }]),
        ),
      ),
    );
    await act(() => i18n.changeLanguage("de"));
    try {
      renderCard();

      const row = await screen.findByTestId("failed-email-row");
      expect(within(row).queryByText(/SMTP is not configured/)).toBeNull();
      expect(within(row).getByText(/^Grund: .*SMTP/)).toBeInTheDocument();
    } finally {
      await act(() => i18n.changeLanguage("en"));
    }
  });
});
