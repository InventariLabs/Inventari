import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import userEvent from "@testing-library/user-event";
import { render, screen } from "@/test/utils";
import { server } from "@/test/mocks/server";
import CostVariancesPage from "./CostVariancesPage";

describe("CostVariancesPage", () => {
  it("lists every variance with its document and adds them up per currency", async () => {
    server.use(
      http.get("*/api/v1/warehouse/cost-variances", () =>
        HttpResponse.json({
          items: [
            {
              id: "v1",
              document_id: "d1",
              document_number: "IN/2026/001",
              kind: "freight",
              amount: "200.00",
              currency: "PLN",
              reason: "Invoiced after posting",
              occurred_on: "2026-11-10",
            },
            {
              id: "v2",
              document_id: "d2",
              document_number: "IN/2026/002",
              kind: "duty",
              amount: "50.50",
              currency: "EUR",
              reason: "Customs bill came later",
              occurred_on: "2026-11-02",
            },
          ],
          totals: { PLN: "200.00", EUR: "50.50" },
          total: 2,
          limit: 50,
          offset: 0,
          has_more: false,
        }),
      ),
    );

    render(<CostVariancesPage />);

    expect(await screen.findByText("IN/2026/001")).toBeInTheDocument();
    expect(screen.getByText("Customs bill came later")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "IN/2026/002" })).toHaveAttribute(
      "href",
      "/warehouse/documents/d2",
    );
    // One total per currency: a variance is never converted.
    expect(screen.getAllByText("Total")).toHaveLength(2);
  });

  it("says plainly that nothing has been recorded", async () => {
    server.use(
      http.get("*/api/v1/warehouse/cost-variances", () =>
        HttpResponse.json({
          items: [],
          totals: {},
          total: 0,
          limit: 50,
          offset: 0,
          has_more: false,
        }),
      ),
    );

    render(<CostVariancesPage />);

    expect(
      await screen.findByText(/No cost has been recorded as a variance/),
    ).toBeInTheDocument();
  });

  it("asks for the next page and keeps the sums of the whole period", async () => {
    const offsets: string[] = [];
    server.use(
      http.get("*/api/v1/warehouse/cost-variances", ({ request }) => {
        const offset = new URL(request.url).searchParams.get("offset") ?? "";
        offsets.push(offset);
        return HttpResponse.json({
          items: [
            {
              id: `v${offset}`,
              document_id: "d1",
              document_number: `IN/${offset}`,
              kind: "freight",
              amount: "10.00",
              currency: "PLN",
              reason: "Late bill",
              occurred_on: "2026-11-10",
            },
          ],
          totals: { PLN: "1000.00" },
          total: 120,
          limit: 50,
          offset: Number(offset),
          has_more: Number(offset) + 50 < 120,
        });
      }),
    );

    render(<CostVariancesPage />);
    expect(await screen.findByText("IN/0")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /next/i }));

    expect(await screen.findByText("IN/50")).toBeInTheDocument();
    expect(offsets).toEqual(["0", "50"]);
  });
});
