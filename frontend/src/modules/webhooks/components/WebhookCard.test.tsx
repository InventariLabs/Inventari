import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { WebhookCard } from "./WebhookCard";
import type { WebhookEndpoint } from "@/modules/webhooks/types/webhooks";

const BASE: WebhookEndpoint = {
  id: "wh-1",
  name: "Warehouse sync",
  url: "https://example.test/hook",
  has_secret: true,
  http_method: "POST",
  event_types: ["item.created"],
  max_retries: 3,
  retry_backoff_seconds: 60,
  timeout_seconds: 10,
  is_active: true,
  last_triggered_at: null,
  last_status_code: null,
  consecutive_failures: 0,
  auto_disabled_at: null,
  events_all_module_disabled: false,
  events_unknown: false,
  created_at: "2026-08-01T10:00:00Z",
  updated_at: "2026-08-01T10:00:00Z",
};

function renderCard(
  webhook: Partial<WebhookEndpoint>,
  onLogs = vi.fn(),
  { onReactivate = vi.fn(), isAdmin = true } = {},
) {
  return render(
    <MemoryRouter>
      <WebhookCard
        webhook={{ ...BASE, ...webhook }}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onTest={vi.fn()}
        onReactivate={onReactivate}
        onLogs={onLogs}
        isAdmin={isAdmin}
      />
    </MemoryRouter>,
  );
}

describe("WebhookCard status", () => {
  it("says an endpoint somebody paused is inactive, and nothing about why", () => {
    // Measured on a fresh endpoint created with is_active: false — no circuit,
    // no failures — and it wore the breaker's badge. An administrator who
    // paused an endpoint for maintenance came back to hunt for deliveries that
    // had never failed.
    renderCard({ is_active: false });

    expect(screen.getByText("Inactive")).toBeInTheDocument();
    expect(screen.queryByText(/circuit breaker/i)).toBeNull();
    expect(screen.queryByText(/auto-disabled/i)).toBeNull();
  });

  it("names the circuit breaker once it has actually acted", () => {
    renderCard({
      is_active: false,
      consecutive_failures: 10,
      auto_disabled_at: "2026-08-20T09:00:00Z",
    });

    expect(screen.getByText("Inactive (circuit breaker)")).toBeInTheDocument();
    expect(screen.getByText(/auto-disabled after 10/i)).toBeInTheDocument();
    expect(
      screen.getByText(/not delivered, queued or logged/i),
    ).toBeInTheDocument();
  });

  it("refers the reader to the delivery log instead of prescribing a URL fix", () => {
    // An unreadable signing secret, a timeout and a receiver's 500 all trip
    // the breaker too; the sentence used to send the administrator to fix the
    // URL whatever the cause had been. The cause of the last attempt is on
    // its own log row, one press away from the card.
    const onLogs = vi.fn();
    renderCard(
      {
        is_active: false,
        consecutive_failures: 10,
        auto_disabled_at: "2026-08-20T09:00:00Z",
      },
      onLogs,
    );

    expect(screen.queryByText(/fix the target url/i)).toBeNull();

    // The banner's referral opens the log for this endpoint; the icon button
    // in the actions row carries the endpoint name in its accessible name,
    // so the bare label is the banner's alone.
    fireEvent.click(screen.getByRole("button", { name: "Delivery logs" }));
    expect(onLogs).toHaveBeenCalledTimes(1);
  });

  it("carries the failure count for a paused endpoint without blaming it", () => {
    // Deliveries had been failing, then a person switched the endpoint off
    // before the threshold. The count is a fact; the cause is not.
    renderCard({ is_active: false, consecutive_failures: 3 });

    expect(screen.getByText("Inactive")).toBeInTheDocument();
    expect(
      screen.getByText("3 failed deliveries since the last successful one."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/auto-disabled/i)).toBeNull();
  });

  it("says nothing about failures on a healthy endpoint", () => {
    renderCard({});

    expect(screen.queryByText("Inactive")).toBeNull();
    expect(screen.queryByText(/failed deliver/i)).toBeNull();
  });

  it("flags an endpoint whose events all belong to disabled modules", () => {
    // The dot still reads active and no delivery has failed — the card looked
    // healthy while nothing it listens for could ever fire. The flag says so.
    renderCard({ events_all_module_disabled: true });

    expect(screen.getByText("Inactive (module disabled)")).toBeInTheDocument();
  });

  it("does not flag an endpoint that can still fire", () => {
    renderCard({ events_all_module_disabled: false });

    expect(screen.queryByText(/module disabled/i)).toBeNull();
  });

  it("flags an endpoint subscribed to a name the catalogue no longer offers", () => {
    // The row keeps item.consumed; the catalogue dropped it, so that half of
    // the subscription can never fire while the card's dot still reads
    // healthy. Review measured exactly that silence on a seeded row.
    renderCard({ events_unknown: true, event_types: ["item.consumed"] });

    expect(screen.getByText("Unknown event names")).toBeInTheDocument();
  });

  it("does not flag a subscription the catalogue still offers", () => {
    renderCard({ events_unknown: false, event_types: ["item.used"] });

    expect(screen.queryByText(/unknown event names/i)).toBeNull();
  });

  describe("the way back from a tripped breaker", () => {
    const TRIPPED = {
      is_active: false,
      consecutive_failures: 10,
      auto_disabled_at: "2026-08-20T09:00:00Z",
    };

    it("offers to turn the endpoint back on from the banner itself", () => {
      // The only other door was the edit form's last switch, under ~40 event
      // checkboxes; a reader fixing the receiver had no hint it existed.
      const onReactivate = vi.fn();
      renderCard(TRIPPED, vi.fn(), { onReactivate });

      fireEvent.click(screen.getByRole("button", { name: /^Reactivate / }));

      expect(onReactivate).toHaveBeenCalledTimes(1);
    });

    it("offers exactly one Reactivate, named after the webhook", () => {
      // The action row used to repeat it, so a phone (where the row spells
      // its labels out) showed the word twice and a screen reader heard two
      // identical buttons.
      renderCard(TRIPPED);

      const buttons = screen.getAllByRole("button", { name: /Reactivate/ });
      expect(buttons).toHaveLength(1);
      expect(buttons[0]).toHaveAccessibleName(`Reactivate ${BASE.name}`);
    });

    it("keeps the icon beside the label instead of stacking it above", () => {
      renderCard(TRIPPED);

      const banner = screen
        .getByText(/auto-disabled after 10/i)
        .closest<HTMLElement>("[class*='bg-yellow-50']")!;
      const button = within(banner).getByRole("button", {
        name: /Reactivate/,
      });
      // `block` replaces the button's `inline-flex`, which is what puts the
      // icon and the word on one line.
      expect(button).toHaveClass("inline-flex");
      expect(button).not.toHaveClass("block");
    });

    it("keeps the row's Reactivate for an endpoint somebody paused", () => {
      renderCard({ is_active: false, auto_disabled_at: null });

      expect(
        screen.getAllByRole("button", { name: /Reactivate/ }),
      ).toHaveLength(1);
    });

    it("keeps the banner's way back from people who cannot use it", () => {
      renderCard(TRIPPED, vi.fn(), { isAdmin: false });

      expect(screen.queryByRole("button", { name: /Reactivate/ })).toBeNull();
    });

    it("keeps the error count in the sentence once a passing test has not reset it", () => {
      renderCard(TRIPPED);

      expect(screen.getByText(/after 10 consecutive/i)).toBeInTheDocument();
    });
  });

  it("writes the live state beside the status dot instead of leaving it to a colour", () => {
    renderCard({ consecutive_failures: 2 });

    expect(screen.getByText("Failing")).toBeInTheDocument();
  });

  it("warns, before the click, that a failed test counts toward the breaker", () => {
    // A test is a real probe: six clicks against a dead receiver switched an
    // endpoint off, and nothing on the button said it could.
    renderCard({});

    expect(screen.getByRole("button", { name: /^Test / })).toHaveAttribute(
      "title",
      expect.stringMatching(/counts toward the circuit breaker/),
    );
  });

  it("names a healthy endpoint as active", () => {
    renderCard({});

    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("paints a healthy endpoint's dot with the success token, which no profile repaints", () => {
    const { container } = renderCard({});

    expect(container.querySelector(".bg-success-500")).not.toBeNull();
    expect(container.querySelector("[class*='bg-accent']")).toBeNull();
  });
});
