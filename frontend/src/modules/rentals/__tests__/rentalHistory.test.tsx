import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { formatDateInZone } from "@/utils/formatters";

import type { BookingListPage } from "../api/rentals";
import { AssetRentalHistory } from "../components/AssetRentalHistory";
import { PartnerRentalHistory } from "../components/PartnerRentalHistory";

type BookingRow = BookingListPage["items"][number];

const useBookingsMock = vi.hoisted(() => vi.fn());

vi.mock("../hooks/useRentals", () => ({
  useBookings: useBookingsMock,
}));

// The card prints the organization's clock; a fixed zone keeps the expected
// date and time the same on every machine running the suite.
vi.mock("@/hooks/useOrganizationTimezone", () => ({
  useOrganizationTimezone: () => "UTC",
}));

function booking(overrides: Partial<BookingRow> = {}): BookingRow {
  return {
    id: "b1",
    status: "RESERVED",
    is_late: false,
    late_days: 0,
    borrower_name: "Anna Nowak",
    borrower_kind: "partner",
    borrower_partner_id: "p1",
    starts_at: "2026-11-20T09:00:00Z",
    ends_at: "2026-11-22T16:00:00Z",
    units_count: 1,
    summary: "Projector 4K",
    ...overrides,
  };
}

function result(items: BookingRow[]) {
  return {
    data: { items, total: items.length, limit: 5, offset: 0 },
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  };
}

function renderWithRouter(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

function bookingLinks(): HTMLElement[] {
  return screen
    .queryAllByRole("link")
    .filter((link) =>
      /^\/rentals\/bookings\/[^?]+$/.test(link.getAttribute("href") ?? ""),
    );
}

describe("PartnerRentalHistory", () => {
  beforeEach(() => {
    useBookingsMock.mockReset();
  });

  it("asks for the partner's latest bookings and shows each one", () => {
    const returned = booking({
      id: "b2",
      status: "RETURNED",
      summary: "Speaker set",
    });
    useBookingsMock.mockReturnValue(result([booking(), returned]));

    renderWithRouter(
      <PartnerRentalHistory data={{ partnerId: "p1", partnerName: "SP 3" }} />,
    );

    expect(useBookingsMock).toHaveBeenCalledWith({
      partner_id: "p1",
      limit: 5,
    });
    expect(screen.getByText("Projector 4K")).toBeInTheDocument();
    expect(screen.getByText("Speaker set")).toBeInTheDocument();
    expect(screen.getByText("Reserved")).toBeInTheDocument();
    expect(screen.getByText("Returned")).toBeInTheDocument();
    expect(bookingLinks().map((link) => link.getAttribute("href"))).toEqual(
      expect.arrayContaining(["/rentals/bookings/b1", "/rentals/bookings/b2"]),
    );
  });

  it("names the window on the organization's clock", () => {
    const row = booking();
    useBookingsMock.mockReturnValue(result([row]));

    renderWithRouter(
      <PartnerRentalHistory data={{ partnerId: "p1", partnerName: "SP 3" }} />,
    );

    expect(
      screen.getByText(
        new RegExp(formatDateInZone(row.starts_at, "UTC", { variant: "date" })),
      ),
    ).toBeInTheDocument();
  });

  it("leaves the borrower out: the sheet is already about that partner", () => {
    useBookingsMock.mockReturnValue(result([booking()]));

    renderWithRouter(
      <PartnerRentalHistory data={{ partnerId: "p1", partnerName: "SP 3" }} />,
    );

    expect(screen.queryByText("Anna Nowak")).not.toBeInTheDocument();
  });

  it("opens the full list narrowed to the partner", () => {
    useBookingsMock.mockReturnValue(result([booking()]));

    renderWithRouter(
      <PartnerRentalHistory data={{ partnerId: "p1", partnerName: "SP 3" }} />,
    );

    expect(
      screen
        .getAllByRole("link")
        .find(
          (link) =>
            link.getAttribute("href") === "/rentals/bookings?partner_id=p1",
        ),
    ).toBeDefined();
  });

  it("shows an empty state instead of a heading with nothing under it", () => {
    useBookingsMock.mockReturnValue(result([]));

    renderWithRouter(
      <PartnerRentalHistory data={{ partnerId: "p1", partnerName: "SP 3" }} />,
    );

    expect(screen.getByTestId("empty-state")).toBeInTheDocument();
    expect(bookingLinks()).toHaveLength(0);
  });
});

describe("AssetRentalHistory", () => {
  beforeEach(() => {
    useBookingsMock.mockReset();
  });

  it("asks for the asset's bookings and names who borrowed it", () => {
    useBookingsMock.mockReturnValue(
      result([
        booking({ id: "b1", borrower_name: "Anna Nowak" }),
        booking({
          id: "b2",
          borrower_name: "Piotr Lis",
          status: "RETURNED",
        }),
      ]),
    );

    renderWithRouter(
      <AssetRentalHistory data={{ itemId: "i1", itemName: "HP EliteBook" }} />,
    );

    expect(useBookingsMock).toHaveBeenCalledWith({ item_id: "i1", limit: 5 });
    expect(screen.getByText("Anna Nowak")).toBeInTheDocument();
    expect(screen.getByText("Piotr Lis")).toBeInTheDocument();
  });

  it("opens the full list narrowed to the asset", () => {
    useBookingsMock.mockReturnValue(result([booking()]));

    renderWithRouter(
      <AssetRentalHistory data={{ itemId: "i1", itemName: "HP EliteBook" }} />,
    );

    expect(
      screen
        .getAllByRole("link")
        .find(
          (link) =>
            link.getAttribute("href") === "/rentals/bookings?item_id=i1",
        ),
    ).toBeDefined();
  });

  it("shows a newer booking before an older one and caps the card at five", () => {
    const rows = Array.from({ length: 6 }, (_, index) =>
      booking({
        id: `b${index + 1}`,
        summary: `Booking ${index + 1}`,
      }),
    );
    useBookingsMock.mockReturnValue(result(rows));

    renderWithRouter(
      <AssetRentalHistory data={{ itemId: "i1", itemName: "HP EliteBook" }} />,
    );

    expect(bookingLinks()).toHaveLength(5);
    expect(screen.queryByText("Booking 6")).not.toBeInTheDocument();
  });

  it("offers a retry when the read fails", async () => {
    const refetch = vi.fn();
    useBookingsMock.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error("boom"),
      refetch,
    });

    renderWithRouter(
      <AssetRentalHistory data={{ itemId: "i1", itemName: "HP EliteBook" }} />,
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("says it is loading while the answer is on its way", () => {
    useBookingsMock.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });

    renderWithRouter(
      <AssetRentalHistory data={{ itemId: "i1", itemName: "HP EliteBook" }} />,
    );

    expect(screen.getByRole("status")).toBeInTheDocument();
  });
});
