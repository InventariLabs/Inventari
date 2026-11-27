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
import { ModulesProvider } from "@/contexts/ModulesContext";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import { onePage } from "@/test/mocks/page";

import TodayPage from "../pages/TodayPage";
import BookingsPage from "../pages/BookingsPage";
import CalendarPage from "../pages/CalendarPage";
import NewBookingPage from "../pages/NewBookingPage";
import PickupPage from "../pages/PickupPage";
import BookingDetailPage from "../pages/BookingDetailPage";
import BlocksPage from "../pages/BlocksPage";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

const ITEM_ID = "11111111-1111-4111-8111-111111111111";
const UNIT_ID = "22222222-2222-4222-8222-222222222222";
const BOOKING_ID = "33333333-3333-4333-8333-333333333333";
const PARTNER_ID = "44444444-4444-4444-8444-444444444444";
const LINE_ID = "55555555-5555-4555-8555-555555555555";

/** An instant a number of days from now, so the fixtures never go stale. */
function daysFromNow(days: number, hour = 9, minute = 0): string {
  const value = new Date();
  value.setUTCDate(value.getUTCDate() + days);
  value.setUTCHours(hour, minute, 0, 0);
  return value.toISOString();
}

const booking = {
  id: BOOKING_ID,
  status: "RESERVED",
  is_late: false,
  late_days: 0,
  borrower_kind: "partner",
  borrower_partner_id: PARTNER_ID,
  borrower_user_id: null,
  borrower_name: "Szkoła Podstawowa nr 3",
  borrower_email: "sekretariat@sp3.example.com",
  starts_at: daysFromNow(5),
  ends_at: daysFromNow(7, 16),
  note: null,
  lines: [
    {
      id: LINE_ID,
      item_id: null,
      item_name: null,
      model: "Projektor 4K",
      quantity: 1,
      resolved_count: 0,
      units: [],
    },
  ],
  created_at: daysFromNow(-6, 10),
  created_by_name: "Marta Kowalska",
  can_pickup: true,
  can_return: false,
  can_cancel: true,
  can_extend: true,
  handed_out_at: null,
  returned_at: null,
};

const pickedBooking = {
  ...booking,
  status: "PICKED_UP",
  can_pickup: false,
  can_return: true,
  can_cancel: false,
  handed_out_at: daysFromNow(5, 10, 4),
  lines: [
    {
      ...booking.lines[0],
      item_id: ITEM_ID,
      item_name: "Projektor 4K #1",
      resolved_count: 1,
      units: [
        {
          id: UNIT_ID,
          item_id: ITEM_ID,
          item_name: "Projektor 4K #1",
          model: "Projektor 4K",
          serial_number: "PRJ-1",
          asset_tag: null,
          assignment_id: "66666666-6666-4666-8666-666666666666",
          condition: null,
          note: null,
          returned_at: null,
        },
      ],
    },
  ],
};

const today = {
  date: daysFromNow(0, 0),
  pickups_count: 3,
  returns_count: 2,
  late_count: 1,
  late: [
    {
      booking_id: BOOKING_ID,
      borrower_name: "Jan Wiśniewski",
      what: "Aparat A7 #1",
      at: daysFromNow(-1, 9),
      until: daysFromNow(-1, 17),
      late_days: 1,
    },
  ],
  pickups: [
    {
      booking_id: BOOKING_ID,
      borrower_name: "Szkoła Podstawowa nr 3",
      what: "Projektor 4K ×2",
      at: daysFromNow(0, 15),
      until: daysFromNow(3, 16),
      late_days: 0,
    },
  ],
  returns: [],
  in_service: [
    {
      id: "77777777-7777-4777-8777-777777777777",
      item_id: ITEM_ID,
      item_name: "Wiertarka udarowa #2",
      model: "Wiertarka udarowa",
      starts_at: daysFromNow(-2, 0),
      ends_at: daysFromNow(4, 0),
      reason: "wymiana szczotek",
      source: "SERVICE",
      booking_id: null,
      borrower_name: null,
      created_at: daysFromNow(-2, 0),
    },
  ],
};

const calendar = {
  starts_at: daysFromNow(-2, 0),
  ends_at: daysFromNow(12, 0),
  groups: [
    {
      model: "Projektor 4K",
      total_units: 3,
      service_units: 1,
      units: [
        {
          item_id: ITEM_ID,
          name: "Projektor 4K #1",
          serial_number: "PRJ-1",
          asset_tag: null,
          status: "AVAILABLE",
          bars: [
            {
              kind: "reserved",
              label: "Szkoła Podstawowa nr 3",
              starts_at: daysFromNow(5),
              ends_at: daysFromNow(7, 16),
              booking_id: BOOKING_ID,
            },
          ],
        },
      ],
      any_unit: [
        {
          booking_id: BOOKING_ID,
          borrower_name: "Szkoła Podstawowa nr 3",
          quantity: 2,
          starts_at: daysFromNow(5),
          ends_at: daysFromNow(7, 16),
          status: "RESERVED",
        },
      ],
    },
  ],
};

const asset = {
  id: ITEM_ID,
  name: "Projektor 4K #1",
  model: "Projektor 4K",
  category_id: null,
  category_name: null,
  status: "AVAILABLE",
  serial_number: "PRJ-1",
  asset_tag: null,
  barcode: "PRJ-1",
};

function mockBase() {
  server.use(
    http.get("/api/v1/rentals/today", () => HttpResponse.json(today)),
    http.get("/api/v1/rentals/calendar", () => HttpResponse.json(calendar)),
    http.get("/api/v1/rentals/bookings", () =>
      HttpResponse.json(
        onePage([
          {
            id: BOOKING_ID,
            status: "RESERVED",
            is_late: false,
            late_days: 0,
            borrower_name: "Szkoła Podstawowa nr 3",
            borrower_kind: "partner",
            starts_at: daysFromNow(5),
            ends_at: daysFromNow(7, 16),
            units_count: 0,
            summary: "Projektor 4K ×2",
          },
        ]),
      ),
    ),
    http.get("/api/v1/rentals/bookings/:id", () => HttpResponse.json(booking)),
    http.get("/api/v1/rentals/models", () =>
      HttpResponse.json([{ model: "Projektor 4K", total_units: 3 }]),
    ),
    http.get("/api/v1/rentals/assets", () => HttpResponse.json([asset])),
    http.get("/api/v1/rentals/categories", () => HttpResponse.json([])),
    http.get("/api/v1/rentals/buffer-rules", () => HttpResponse.json([])),
    http.get("/api/v1/rentals/blocks", () => HttpResponse.json(onePage([]))),
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

function renderPage(
  element: React.ReactElement,
  route = "/rentals",
  path?: string,
) {
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
        <MemoryRouter initialEntries={[route]}>
          <HeaderHost>
            {path ? (
              <Routes>
                <Route path={path} element={element} />
              </Routes>
            ) : (
              element
            )}
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

describe("rentals screens", () => {
  it("Today shows the day's counts, the late loan and the unit in service", async () => {
    renderPage(<TodayPage />);
    await screen.findByText("3");
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText(/Jan Wiśniewski/)).toBeInTheDocument();
    expect(screen.getByText(/Aparat A7 #1/)).toBeInTheDocument();
    expect(screen.getByText(/was due/)).toBeInTheDocument();
    expect(screen.getByText(/wymiana szczotek/)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Calendar" })).toBeInTheDocument();
  });

  it("the bookings list searches and shows the state", async () => {
    renderPage(<BookingsPage />);
    await screen.findByText("Szkoła Podstawowa nr 3");
    expect(screen.getByText("Projektor 4K ×2")).toBeInTheDocument();
    expect(screen.getAllByText("Reserved").length).toBeGreaterThan(0);
  });

  it("the calendar groups by model and has an any-unit row", async () => {
    renderPage(<CalendarPage />);
    await screen.findAllByText("Projektor 4K");
    expect(screen.getByText("any unit")).toBeInTheDocument();
    expect(
      screen.getAllByText(/Szkoła Podstawowa nr 3/).length,
    ).toBeGreaterThan(0);
    expect(screen.getByText(/3 units/)).toBeInTheDocument();
  });

  it("a booking whose lines fit enables Save and posts model lines", async () => {
    let posted: Record<string, unknown> | null = null;
    server.use(
      http.post("/api/v1/rentals/bookings/check", () =>
        HttpResponse.json({
          ok: true,
          lines: [
            {
              index: 0,
              ok: true,
              label: "Projektor 4K ×1",
              requested: 1,
              available: 3,
              conflicts: [],
              max_quantity: 3,
              nearest_window: null,
            },
          ],
        }),
      ),
      http.post("/api/v1/rentals/bookings", async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(booking, { status: 201 });
      }),
    );
    const user = renderPage(<NewBookingPage />);
    const partner = await screen.findByLabelText("Partner");
    await screen.findByRole("option", { name: "Szkoła Podstawowa nr 3" });
    await user.selectOptions(partner, PARTNER_ID);
    const save = await screen.findByRole("button", { name: "Book" });
    await waitFor(() => expect(save).toBeEnabled());
    // The sheet says how many of the model's units the window leaves free.
    expect(await screen.findByText("3 of 3 available")).toBeInTheDocument();
    await user.click(save);
    await waitFor(() => expect(posted).not.toBeNull());
    const lines = (posted as unknown as { lines: { model: string }[] }).lines;
    expect(lines[0].model).toBe("Projektor 4K");
  });

  it("a line that does not fit says why and keeps Save off", async () => {
    server.use(
      http.post("/api/v1/rentals/bookings/check", () =>
        HttpResponse.json({
          ok: false,
          lines: [
            {
              index: 0,
              ok: false,
              label: "Projektor 4K ×2",
              requested: 2,
              available: 1,
              conflicts: [
                {
                  item_id: ITEM_ID,
                  item_name: "Projektor 4K #1",
                  kind: "reserved",
                  label: "Szkoła Podstawowa nr 3",
                  starts_at: daysFromNow(5),
                  ends_at: daysFromNow(7, 16),
                  booking_id: BOOKING_ID,
                  reason: null,
                },
              ],
              max_quantity: 1,
              nearest_window: {
                starts_at: daysFromNow(9),
                ends_at: daysFromNow(11, 16),
              },
            },
          ],
        }),
      ),
    );
    const user = renderPage(<NewBookingPage />);
    await screen.findByRole("option", { name: "Szkoła Podstawowa nr 3" });
    await user.selectOptions(screen.getByLabelText("Partner"), PARTNER_ID);
    await screen.findByText(/Only 1 of 2 are free/);
    expect(screen.getByRole("button", { name: "Book" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: /Reduce to 1 unit/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Move to/ })).toBeInTheDocument();
  });

  it("pickup is confirmed only after every unit is chosen", async () => {
    let posted: { item_ids: string[] } | null = null;
    server.use(
      http.get("/api/v1/rentals/bookings/:id", () =>
        HttpResponse.json({
          ...booking,
          lines: [
            {
              ...booking.lines[0],
              quantity: 1,
            },
          ],
        }),
      ),
      http.post("/api/v1/rentals/bookings/:id/pickup", async ({ request }) => {
        posted = (await request.json()) as { item_ids: string[] };
        return HttpResponse.json(pickedBooking);
      }),
    );
    const user = renderPage(
      <PickupPage />,
      `/rentals/bookings/${BOOKING_ID}/pickup`,
      "/rentals/bookings/:id/pickup",
    );
    await screen.findByText(/Projektor 4K · any unit/);
    // The header counts what is covered; a plural key read without `count`
    // rendered the raw i18n key here.
    expect(await screen.findByText("To hand out · 0 of 1")).toBeInTheDocument();
    const confirm = await screen.findByRole("button", {
      name: /Confirm the hand-out \(1 line missing\)/,
    });
    expect(confirm).toBeDisabled();
    await user.selectOptions(
      screen.getByLabelText(/Choose Projektor 4K · any unit/),
      ITEM_ID,
    );
    await user.click(
      screen.getByRole("button", { name: "Confirm the hand-out" }),
    );
    await waitFor(() => expect(posted).not.toBeNull());
    expect((posted as unknown as { item_ids: string[] }).item_ids).toEqual([
      ITEM_ID,
    ]);
  });

  it("a return records the condition of every unit", async () => {
    let posted: { units: { condition: string }[] } | null = null;
    server.use(
      http.get("/api/v1/rentals/bookings/:id", () =>
        HttpResponse.json(pickedBooking),
      ),
      http.post("/api/v1/rentals/bookings/:id/return", async ({ request }) => {
        posted = (await request.json()) as { units: { condition: string }[] };
        return HttpResponse.json({ ...pickedBooking, status: "RETURNED" });
      }),
    );
    const user = renderPage(
      <BookingDetailPage />,
      `/rentals/bookings/${BOOKING_ID}`,
      "/rentals/bookings/:id",
    );
    await screen.findByText("Return");
    await user.click(
      screen.getByRole("button", { name: "Confirm the return" }),
    );
    await waitFor(() => expect(posted).not.toBeNull());
    expect(
      (posted as unknown as { units: { condition: string }[] }).units[0]
        .condition,
    ).toBe("GOOD");
  });

  it("service blocks and buffer rules render together", async () => {
    renderPage(<BlocksPage />);
    await screen.findByRole("heading", { name: "Service blocks" });
    expect(screen.getByText("Buffer time")).toBeInTheDocument();
    expect(
      screen.getByText(
        /No buffer rules; bookings may follow one another immediately/,
      ),
    ).toBeInTheDocument();
  });
});
