import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { AssetTimeline } from "./AssetTimeline";
import { useAssetTimeline } from "@/modules/equipment/hooks/useEquipment";
import { render } from "@/test/utils";
import { server } from "@/test/mocks/server";
import type { Item } from "@/types";
import type { AssetTimelineEvent } from "@/modules/equipment/api/equipment_timeline";

vi.mock("@/modules/equipment/hooks/useEquipment", () => ({
  useAssetTimeline: vi.fn(),
}));

const useAssetTimelineMock = vi.mocked(useAssetTimeline);

const item = {
  id: "item-1",
  name: "Laptop",
  created_at: "2026-08-01T10:00:00Z",
  brand: "Dell",
  metadata: {},
} as unknown as Item;

let seq = 0;

/** A server event, with the bookkeeping the endpoint fills in. */
function event(
  overrides: Partial<AssetTimelineEvent> & Pick<AssetTimelineEvent, "kind">,
): AssetTimelineEvent {
  seq += 1;
  return {
    id: `row-${seq}`,
    date: `2026-08-0${(seq % 8) + 1}T09:00:00Z`,
    ...overrides,
  };
}

/** A read in the shape the hook returns, defaulting to a quiet success. */
function read(overrides: Record<string, unknown> = {}) {
  return {
    data: [] as AssetTimelineEvent[],
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
    ...overrides,
  } as unknown as ReturnType<typeof useAssetTimeline>;
}

/**
 * The timeline reads one server-assembled feed that already carries the
 * asset's creation and is already ordered — nothing is appended around it.
 * These tests fail on any of: the feed not being the source, a status
 * change not rendering, a same-day repair sinking below older events, and
 * the handover losing the name of who actually did what.
 */
describe("AssetTimeline", () => {
  it("says the timeline could not be read", async () => {
    useAssetTimelineMock.mockReturnValue(
      read({ isError: true, error: new Error("boom") }),
    );

    render(<AssetTimeline item={item} />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText("No history yet")).not.toBeInTheDocument();
  });

  it("says so when the feed carries no events", () => {
    useAssetTimelineMock.mockReturnValue(read());

    render(<AssetTimeline item={item} />);

    expect(screen.getByText("No history yet")).toBeInTheDocument();
  });

  it("renders the created entry the feed opens with", () => {
    useAssetTimelineMock.mockReturnValue(
      read({
        data: [event({ kind: "created", date: "2026-08-01T10:00:00Z" })],
      }),
    );

    render(<AssetTimeline item={item} />);

    expect(screen.getByText("Asset created")).toBeInTheDocument();
    expect(screen.getByText("Dell")).toBeInTheDocument();
    expect(screen.queryByText("No history yet")).not.toBeInTheDocument();
  });

  it("shows status changes, including a retirement and its reversal", () => {
    useAssetTimelineMock.mockReturnValue(
      read({
        data: [
          event({
            kind: "status_changed",
            old_status: "AVAILABLE",
            new_status: "RETIRED",
            date: "2026-08-02T09:00:00Z",
          }),
          event({
            kind: "status_changed",
            old_status: "RETIRED",
            new_status: "AVAILABLE",
            date: "2026-08-03T09:00:00Z",
          }),
        ],
      }),
    );

    render(<AssetTimeline item={item} />);

    expect(screen.getAllByText("Status changed")).toHaveLength(2);
    expect(screen.getByText("Retired → Available")).toBeInTheDocument();
    expect(screen.getByText("Available → Retired")).toBeInTheDocument();
  });

  // A problem reported in an attestation lived on the campaign's response
  // alone; the asset it was about said nothing.
  it("shows a problem the holder reported in an attestation", () => {
    useAssetTimelineMock.mockReturnValue(
      read({
        data: [
          event({
            kind: "attestation_disputed",
            holder_name: "Ava Brennan",
            title: "Autumn equipment check",
            condition: "DAMAGED",
            notes: "Cracked screen",
            date: "2026-10-20T09:00:00Z",
          }),
        ],
      }),
    );

    render(<AssetTimeline item={item} />);

    expect(
      screen.getByText("Problem reported by Ava Brennan"),
    ).toBeInTheDocument();
    expect(screen.getByText("Autumn equipment check")).toBeInTheDocument();
    expect(screen.getByText("Cracked screen")).toBeInTheDocument();
  });

  it("skips a kind it cannot name instead of calling it a status change", () => {
    useAssetTimelineMock.mockReturnValue(
      read({
        data: [
          event({ kind: "created" }),
          event({
            kind: "relabelled" as AssetTimelineEvent["kind"],
            old_status: "AVAILABLE",
            new_status: "RETIRED",
          }),
        ],
      }),
    );

    render(<AssetTimeline item={item} />);

    expect(screen.getByText("Asset created")).toBeInTheDocument();
    expect(screen.queryByText("Status changed")).not.toBeInTheDocument();
    expect(screen.queryByText("Available → Retired")).not.toBeInTheDocument();
  });

  it("names both people when someone else checked the return off", () => {
    useAssetTimelineMock.mockReturnValue(
      read({
        data: [
          event({
            kind: "checkout",
            holder_name: "Anna Nowak",
            holder_email: "anna@example.com",
            issued_by_name: "Admin",
            date: "2026-08-01T10:00:00Z",
          }),
          event({
            kind: "checkin",
            holder_name: "Anna Nowak",
            operator_name: "QA Admin",
            condition: "NEEDS_REPAIR",
            date: "2026-08-05T10:00:00Z",
          }),
        ],
      }),
    );

    render(<AssetTimeline item={item} />);

    expect(screen.getByText("Checked out to Anna Nowak")).toBeInTheDocument();
    expect(screen.getByText("Issued by: Admin")).toBeInTheDocument();
    expect(
      screen.getByText("Returned for Anna Nowak by QA Admin"),
    ).toBeInTheDocument();
  });

  it("says a deployment was placed in a location, never handed to a person", () => {
    useAssetTimelineMock.mockReturnValue(
      read({
        data: [
          event({
            kind: "checkout",
            holder_name: "Server Rack A",
            holder_kind: "location",
            issued_by_name: "Admin",
            date: "2026-08-01T10:00:00Z",
          }),
          event({
            kind: "checkin",
            holder_name: "Server Rack A",
            holder_kind: "location",
            operator_name: "QA Admin",
            date: "2026-08-05T10:00:00Z",
          }),
        ],
      }),
    );

    render(<AssetTimeline item={item} />);

    expect(
      screen.getByText("Checked out to Server Rack A"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Returned from Server Rack A by QA Admin"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Returned for/)).not.toBeInTheDocument();
  });

  it("credits the holder alone when they returned it themselves", () => {
    useAssetTimelineMock.mockReturnValue(
      read({
        data: [
          event({
            kind: "checkin",
            holder_name: "Anna Nowak",
            operator_name: "Anna Nowak",
          }),
        ],
      }),
    );

    render(<AssetTimeline item={item} />);

    expect(screen.getByText("Returned by Anna Nowak")).toBeInTheDocument();
    expect(
      screen.queryByText("Returned for Anna Nowak by Anna Nowak"),
    ).not.toBeInTheDocument();
  });

  it("claims nobody when the operator account is unknown", () => {
    useAssetTimelineMock.mockReturnValue(
      read({
        data: [
          event({
            kind: "checkin",
            holder_name: "Anna Nowak",
            operator_name: null,
          }),
        ],
      }),
    );

    render(<AssetTimeline item={item} />);

    expect(screen.getByText("Returned")).toBeInTheDocument();
  });

  it("keeps what a repair cost on the timeline", () => {
    useAssetTimelineMock.mockReturnValue(
      read({
        data: [
          event({
            kind: "maintenance",
            maintenance_type: "REPAIR",
            title: "Hinge",
            cost: "120.50",
            currency: "PLN",
          }),
        ],
      }),
    );

    render(<AssetTimeline item={item} />);

    expect(screen.getByText("Repair: Hinge")).toBeInTheDocument();
    expect(screen.getByText(/120[.,]50/)).toBeInTheDocument();
  });

  it("reads a bare maintenance day as the whole day it names", () => {
    // The feed arrives ordered: a repair entered today stands above the
    // asset's creation even though a date-only value has no moment in it.
    // Read as midnight it would sink below everything timestamped — the
    // ordering belongs to whoever keeps the day as a day.
    useAssetTimelineMock.mockReturnValue(
      read({
        data: [
          event({
            kind: "maintenance",
            maintenance_type: "REPAIR",
            title: "Today",
            date: "2026-09-06",
          }),
          event({ kind: "created", date: "2026-08-01T10:00:00Z" }),
        ],
      }),
    );

    const { container } = render(<AssetTimeline item={item} />);

    const list = container.firstElementChild as HTMLElement;
    const entries = within(list).getAllByText(/Repair: Today|Asset created/);
    expect(entries).toHaveLength(2);
    expect(entries[0].textContent).toContain("Repair: Today");
    expect(
      entries[0].compareDocumentPosition(entries[1]) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("reads the expected return day on the organization's clock", async () => {
    // The checkout stored "2026-09-30T00:00:00Z" — UTC midnight. A reader
    // in Los Angeles used to see 09/29 off it; the timeline owes the
    // organization's clock, like every other read of this day.
    useAssetTimelineMock.mockReturnValue(
      read({
        data: [
          event({
            kind: "checkout",
            holder_name: "Anna Nowak",
            expected_return_at: "2026-09-30T00:00:00Z",
            date: "2026-09-01T10:00:00Z",
          }),
        ],
      }),
    );
    server.use(
      http.get("/api/v1/organizations/my", () =>
        HttpResponse.json({ timezone: "UTC" }),
      ),
    );

    const original = process.env.TZ;
    process.env.TZ = "America/Los_Angeles";
    try {
      render(<AssetTimeline item={item} />);

      expect(
        await screen.findByText(/Expected return: Sep 30, 2026/),
      ).toBeInTheDocument();
      expect(screen.queryByText(/Sep 29, 2026/)).not.toBeInTheDocument();
    } finally {
      process.env.TZ = original;
    }
  });
});
