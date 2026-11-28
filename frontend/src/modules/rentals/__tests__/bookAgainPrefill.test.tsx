import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { withModules } from "@/test/moduleList";
import { onePage } from "@/test/mocks/page";
import { tFor } from "@/test/mocks/i18n";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { formatDate } from "@/utils/formatters";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";

import NewBookingPage from "../pages/NewBookingPage";
import { addDays, isoDate } from "../lib/datetime";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

const t = tFor("rentals");

const KIT_ID = "11111111-1111-4111-8111-111111111111";
const BOOKING_ID = "22222222-2222-4222-8222-222222222222";
const PARTNER_ID = "33333333-3333-4333-8333-333333333333";
const ITEM_ID = "44444444-4444-4444-8444-444444444444";

/** An instant a number of days from now, so the fixtures never go stale. */
function daysFromNow(days: number, hour = 9, minute = 0): string {
  const value = new Date();
  value.setUTCDate(value.getUTCDate() + days);
  value.setUTCHours(hour, minute, 0, 0);
  return value.toISOString();
}

/** A booking ten days ago: its next week is already in the past. */
const booking = {
  id: BOOKING_ID,
  status: "RETURNED",
  is_late: false,
  late_days: 0,
  borrower_kind: "partner",
  borrower_partner_id: PARTNER_ID,
  borrower_user_id: null,
  borrower_name: "Szkoła Podstawowa nr 3",
  borrower_email: "sekretariat@sp3.example.com",
  starts_at: daysFromNow(-10, 9),
  ends_at: daysFromNow(-8, 16),
  note: "Collect at the office",
  lines: [
    {
      id: "55555555-5555-4555-8555-555555555551",
      item_id: null,
      item_name: null,
      model: "Projektor 4K",
      quantity: 1,
      resolved_count: 1,
      kit_id: KIT_ID,
      kit_name: "Fotografia",
      units: [],
    },
    {
      id: "55555555-5555-4555-8555-555555555552",
      item_id: ITEM_ID,
      item_name: "Aparat A7 #1",
      model: "Aparat A7",
      quantity: 1,
      resolved_count: 1,
      kit_id: KIT_ID,
      kit_name: "Fotografia",
      units: [],
    },
    {
      id: "55555555-5555-4555-8555-555555555553",
      item_id: null,
      item_name: null,
      model: "Projektor 4K",
      quantity: 2,
      resolved_count: 0,
      kit_id: null,
      kit_name: null,
      units: [],
    },
  ],
  created_at: daysFromNow(-11, 10),
  created_by_name: "Marta Kowalska",
  can_pickup: false,
  can_return: false,
  can_cancel: false,
  can_extend: false,
  returned_count: 2,
  outstanding_count: 0,
  handed_out_at: daysFromNow(-10, 9),
  returned_at: daysFromNow(-8, 16),
};

function mockBase() {
  server.use(
    http.get("/api/v1/rentals/bookings/:id", () => HttpResponse.json(booking)),
    http.get("/api/v1/rentals/models", () =>
      HttpResponse.json([{ model: "Projektor 4K", total_units: 3 }]),
    ),
    http.get("/api/v1/rentals/assets", () => HttpResponse.json([])),
    http.get("/api/v1/rentals/kits", () =>
      HttpResponse.json([
        {
          id: KIT_ID,
          name: "Fotografia",
          code: "KIT-AAAA1111",
          member_count: 2,
          summary: "Projektor 4K, Aparat A7 #1",
        },
      ]),
    ),
    http.get("/api/v1/partners", () =>
      HttpResponse.json(
        onePage([
          {
            id: PARTNER_ID,
            name: "Szkoła Podstawowa nr 3",
            email: "sekretariat@sp3.example.com",
          },
        ]),
      ),
    ),
    http.get("/api/v1/users/org-members", () => HttpResponse.json(onePage([]))),
  );
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  function HeaderHost({ children }: { children: React.ReactNode }) {
    const [data, setData] = React.useState<PageHeaderData>({});
    return (
      <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
        {children}
      </PageHeaderContext.Provider>
    );
  }
  render(
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter
          initialEntries={[`/rentals/bookings/new?from=${BOOKING_ID}`]}
        >
          <HeaderHost>
            <Routes>
              <Route
                path="/rentals/bookings/new"
                element={<NewBookingPage />}
              />
            </Routes>
          </HeaderHost>
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

beforeEach(() => {
  signInWith(["rentals:read", "rentals:write"]);
  withModules("rentals", "equipment");
  mockBase();
});

afterEach(() => {
  signOut();
});

describe("book again", () => {
  it("fills the form once and books a kit plus the other lines", async () => {
    let posted: { lines: Record<string, unknown>[] } | null = null;
    server.use(
      http.post("/api/v1/rentals/bookings/check", () =>
        HttpResponse.json({
          ok: true,
          lines: [
            {
              index: 0,
              ok: true,
              label: "Fotografia",
              requested: 1,
              available: 1,
              conflicts: [],
              max_quantity: 1,
              nearest_window: null,
            },
            {
              index: 1,
              ok: true,
              label: "Projektor 4K ×2",
              requested: 2,
              available: 3,
              conflicts: [],
              max_quantity: 3,
              nearest_window: null,
            },
          ],
        }),
      ),
      http.post("/api/v1/rentals/bookings", async ({ request }) => {
        posted = (await request.json()) as { lines: Record<string, unknown>[] };
        return HttpResponse.json(booking, { status: 201 });
      }),
    );
    const user = renderPage();

    // The borrower, the note and the two lines (the kit's members collapsed
    // into one kit line) arrive from the source booking.
    expect(
      await screen.findByText(
        t("form.bookAgainHint", { name: booking.borrower_name }),
      ),
    ).toBeInTheDocument();
    expect(await screen.findByLabelText("Partner")).toHaveValue(PARTNER_ID);
    expect(screen.getByLabelText(t("form.note"))).toHaveValue(booking.note);
    expect(screen.getByLabelText(t("form.chooseKit"))).toHaveValue(KIT_ID);
    expect(screen.getByLabelText(t("form.model"))).toHaveValue("Projektor 4K");

    // The original week is in the past, so the new booking starts tomorrow at
    // the original time and keeps the original duration.
    const tomorrow = addDays(isoDate(new Date().toISOString()), 1);
    expect(
      screen.getByLabelText(t("form.dateOf", { label: t("form.pickup") })),
    ).toHaveTextContent(formatDate(tomorrow));
    expect(
      screen.getByLabelText(t("form.timeOf", { label: t("form.pickup") })),
    ).toHaveValue("09:00");

    const book = await screen.findByRole("button", { name: t("form.save") });
    await waitFor(() => expect(book).toBeEnabled());
    await user.click(book);
    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted!.lines).toEqual([
      { kit_id: KIT_ID },
      { model: "Projektor 4K", quantity: 2 },
    ]);
  });
});
