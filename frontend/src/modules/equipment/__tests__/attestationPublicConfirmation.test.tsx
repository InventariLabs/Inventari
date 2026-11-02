import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import PublicApp from "@/PublicApp";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
  Toaster: () => null,
}));

/**
 * One tap on "I have this asset" recorded a confirmation that the link then
 * refused to take back, and "Missing" — the gravest answer — was already
 * chosen when the report form opened.
 */
const PENDING = {
  id: "resp-1",
  token: "tok-1",
  status: "PENDING",
  assignee_name: "Nina",
  assignee_email: "nina@example.com",
  campaign_name: "Annual check",
  items: [
    {
      id: "ri-1",
      assignment_id: "asg-1",
      item_id: "itm-1",
      item_name: "ThinkPad T14",
      serial_number: "SN-9911",
      returned: false,
    },
  ],
};

let confirmed: boolean;
let disputed: Record<string, unknown> | null;

beforeEach(() => {
  confirmed = false;
  disputed = null;
  server.use(
    http.get("/public/attestation/tok-1", () => HttpResponse.json(PENDING)),
    http.post("/public/attestation/tok-1/confirm", () => {
      confirmed = true;
      return HttpResponse.json({ ...PENDING, status: "CONFIRMED" });
    }),
    http.post("/public/attestation/tok-1/dispute", async ({ request }) => {
      disputed = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json({ ...PENDING, status: "DISPUTED" });
    }),
  );
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <PublicApp initialEntries={["/public/attestation/tok-1"]} />
    </QueryClientProvider>,
  );
});

describe("confirming on the public attestation link", () => {
  it("asks once before it records anything", async () => {
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "I have this asset" }),
    );

    expect(confirmed).toBe(false);
    await user.click(
      await screen.findByRole("button", { name: /Yes, I have it/ }),
    );

    await waitFor(() => expect(confirmed).toBe(true));
  });

  it("goes back without recording when the tap was a slip", async () => {
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "I have this asset" }),
    );
    await user.click(await screen.findByRole("button", { name: "Back" }));

    expect(
      screen.getByRole("button", { name: "I have this asset" }),
    ).toBeInTheDocument();
    expect(confirmed).toBe(false);
  });
});

describe("reporting an issue on the public attestation link", () => {
  it("starts with no issue type chosen and will not submit without one", async () => {
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: /Report Issue/i }),
    );
    await user.type(
      await screen.findByLabelText(/details/i),
      "Something is wrong",
    );

    expect(
      screen.getByRole("combobox", { name: /issue type/i }),
    ).toHaveTextContent(/select/i);
    expect(
      screen.getByRole("button", { name: /submit report/i }),
    ).toBeDisabled();
    expect(disputed).toBeNull();
  });
});
