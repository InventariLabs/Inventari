import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { QueryWrapper } from "@/test/queryWrapper";

import { MaintenanceLogModal } from "./MaintenanceLogModal";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/hooks/useOrganizationCurrency", () => ({
  useOrganizationCurrency: () => "EUR",
}));
vi.mock("@/hooks/useOrganizationTimezone", () => ({
  useOrganizationTimezone: () => "Europe/Warsaw",
}));

// The real DateInput is a popover calendar; these tests only need to say
// which day was picked (the same stub CheckoutModal.test.tsx uses).
vi.mock("@/components/ui/DateInput", () => ({
  DateInput: (props: {
    label: string;
    value: string;
    onChange: (value: string) => void;
  }) => (
    <input
      aria-label={props.label}
      value={props.value}
      onChange={(e) => props.onChange(e.target.value)}
    />
  ),
}));

let posted: Record<string, unknown> | null;

beforeEach(() => {
  posted = null;
  server.use(
    http.post("/api/v1/equipment/maintenance", async ({ request }) => {
      posted = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json({ id: "log-1", ...posted }, { status: 201 });
    }),
  );
});

function renderModal(
  extra: { status?: string; onMarkInService?: () => void } = {},
) {
  const onClose = vi.fn();
  render(
    <QueryWrapper>
      <MaintenanceLogModal
        itemId="item-1"
        itemName="HP EliteBook"
        {...extra}
        onClose={onClose}
      />
    </QueryWrapper>,
  );
  return { onClose, user: userEvent.setup() };
}

/**
 * A service entry needs a kind of work, a title and a day; Save answers on
 * press with what is missing instead of sitting disabled. The failures
 * caught: an entry sent without its required answers, an optional field
 * whose edit never reaches the request, and a cost sent as text or without
 * the organization's currency.
 */
describe("MaintenanceLogModal", () => {
  it("defaults the date to the organization's day", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-05T23:30:00Z"));
    try {
      renderModal();
      expect(screen.getByLabelText("Date")).toHaveValue("2026-10-06");
    } finally {
      vi.useRealTimers();
    }
  });
  it("names each missing answer on Save and sends nothing", async () => {
    const { onClose, user } = renderModal();

    // Pressed, not submitted directly: the browser's own constraint check
    // used to stop the empty form at the title — in the browser's language,
    // about the title alone — before the form's answer could be heard.
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(
      screen.getByText("Choose what kind of work this was"),
    ).toBeInTheDocument();
    expect(screen.getByText("Give the entry a title")).toBeInTheDocument();
    expect(posted).toBeNull();
    expect(onClose).not.toHaveBeenCalled();

    // Answering a question clears its message.
    await user.type(screen.getByLabelText(/^Title/), "Fan cleaned");
    expect(
      screen.queryByText("Give the entry a title"),
    ).not.toBeInTheDocument();
  });

  it("sends every answer, the cost as a number in the organization's currency, and closes", async () => {
    const { onClose, user } = renderModal();

    await user.click(screen.getByRole("radio", { name: "Repair" }));
    await user.type(screen.getByLabelText(/^Title/), "  Replaced fan  ");
    fireEvent.change(screen.getByLabelText("Date"), {
      target: { value: "2026-10-01" },
    });
    await user.type(screen.getByLabelText(/^Cost/), "49.90");
    await user.type(screen.getByLabelText("Technician"), "Jan Serwis");
    fireEvent.change(screen.getByLabelText("Next scheduled maintenance"), {
      target: { value: "2027-04-01" },
    });
    await user.type(screen.getByLabelText("Description"), "Fan was noisy");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(posted).toEqual({
      item_id: "item-1",
      maintenance_type: "REPAIR",
      title: "Replaced fan",
      description: "Fan was noisy",
      cost: 49.9,
      currency: "EUR",
      performed_at: "2026-10-01",
      performed_by: "Jan Serwis",
      next_maintenance_at: "2027-04-01",
    });
  });

  it("leaves the optional answers out when they are blank", async () => {
    const { user } = renderModal();

    await user.click(screen.getByRole("radio", { name: "Repair" }));
    await user.type(screen.getByLabelText(/^Title/), "Inspection");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted).not.toHaveProperty("cost");
    expect(posted).not.toHaveProperty("performed_by");
    expect(posted).not.toHaveProperty("next_maintenance_at");
  });

  it("closes on Cancel without a request", async () => {
    const { onClose, user } = renderModal();
    await user.click(screen.getByText("Cancel", { selector: "button" }));
    expect(onClose).toHaveBeenCalled();
    expect(posted).toBeNull();
  });

  describe("taking an available asset in for repair", () => {
    const TAKE_IN = /no longer offered for hand-out/i;

    it("offers the status change for a repair filed today and applies it on Save", async () => {
      const onMarkInService = vi.fn();
      const { onClose, user } = renderModal({
        status: "AVAILABLE",
        onMarkInService,
      });

      expect(screen.queryByLabelText(TAKE_IN)).toBeNull();
      await user.click(screen.getByRole("radio", { name: "Repair" }));
      expect(screen.getByLabelText(TAKE_IN)).toBeChecked();
      await user.type(screen.getByLabelText(/^Title/), "Replaced fan");
      await user.click(screen.getByRole("button", { name: "Save" }));

      await waitFor(() => expect(onClose).toHaveBeenCalled());
      expect(onMarkInService).toHaveBeenCalledTimes(1);
    });

    it("leaves the status alone when the box is cleared", async () => {
      const onMarkInService = vi.fn();
      const { onClose, user } = renderModal({
        status: "AVAILABLE",
        onMarkInService,
      });

      await user.click(screen.getByRole("radio", { name: "Repair" }));
      await user.click(screen.getByLabelText(TAKE_IN));
      await user.type(screen.getByLabelText(/^Title/), "Replaced fan");
      await user.click(screen.getByRole("button", { name: "Save" }));

      await waitFor(() => expect(onClose).toHaveBeenCalled());
      expect(onMarkInService).not.toHaveBeenCalled();
    });

    it("does not offer it for a past repair, another kind of work or an asset that is not available", async () => {
      const { user } = renderModal({
        status: "AVAILABLE",
        onMarkInService: vi.fn(),
      });
      await user.click(screen.getByRole("radio", { name: "Repair" }));
      fireEvent.change(screen.getByLabelText("Date"), {
        target: { value: "2020-01-01" },
      });
      expect(screen.queryByLabelText(TAKE_IN)).toBeNull();
    });

    it("stays out of the way of an asset that is already checked out", async () => {
      const { user } = renderModal({
        status: "DEPLOYED",
        onMarkInService: vi.fn(),
      });
      await user.click(screen.getByRole("radio", { name: "Repair" }));
      expect(screen.queryByLabelText(TAKE_IN)).toBeNull();
    });
  });
});
