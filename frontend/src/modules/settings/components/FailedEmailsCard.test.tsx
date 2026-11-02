import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
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
});
