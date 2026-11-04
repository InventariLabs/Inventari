import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import PublicApp from "@/PublicApp";
import { formatDate } from "@/utils/formatters";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
  Toaster: () => null,
}));

/**
 * A person who followed the emailed link saw "Inventari" and nothing else:
 * not who was asking, not by when, and "this asset" over a list of three.
 */
function item(n: number) {
  return {
    id: `ri-${n}`,
    assignment_id: `asg-${n}`,
    item_id: `itm-${n}`,
    item_name: `Laptop ${n}`,
    serial_number: `SN-${n}`,
    returned: false,
    status: "PENDING",
  };
}

function open(items: ReturnType<typeof item>[]) {
  server.use(
    http.get("/public/attestation/tok-1", () =>
      HttpResponse.json({
        id: "resp-1",
        token: "tok-1",
        status: "PENDING",
        assignee_name: "Nina",
        assignee_email: "nina@example.com",
        campaign_name: "Annual check",
        organization_name: "Acme Ltd",
        deadline_day: "2026-11-18",
        items,
      }),
    ),
  );
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <PublicApp initialEntries={["/public/attestation/tok-1"]} />
    </QueryClientProvider>,
  );
}

describe("the public attestation page", () => {
  it("names who asks and by which day", async () => {
    open([item(1)]);

    expect(await screen.findByText("Requested by Acme Ltd")).toBeVisible();
    expect(
      screen.getByText(`Please answer by ${formatDate("2026-11-18")}`),
    ).toBeVisible();
  });

  it("speaks of one asset when there is one", async () => {
    const user = userEvent.setup();
    open([item(1)]);

    await user.click(
      await screen.findByRole("button", { name: "I have this asset" }),
    );
    expect(screen.getByText("Confirm that you have this asset?")).toBeVisible();
  });

  it("speaks of the assets when there are several", async () => {
    const user = userEvent.setup();
    open([item(1), item(2), item(3)]);

    await user.click(
      await screen.findByRole("button", { name: "I have these assets" }),
    );
    expect(
      screen.getByText("Confirm that you have these assets?"),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: /Yes, I have them/ }),
    ).toBeVisible();
  });
});
