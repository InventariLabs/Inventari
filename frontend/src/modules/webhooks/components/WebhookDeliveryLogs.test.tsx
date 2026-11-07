import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import WebhookDeliveryLogs from "./WebhookDeliveryLogs";

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    enabledModules: ["webhooks"],
    isModuleEnabled: () => true,
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

const HTML_PAGE = `<!doctype html><html><head><title>405</title></head><body>${"x".repeat(2000)}</body></html>`;

function mockDelivery(overrides: Record<string, unknown>) {
  server.use(
    http.get("*/webhooks/endpoints/:id/deliveries", () =>
      HttpResponse.json({
        items: [
          {
            id: "d-1",
            event_type: "item.created",
            payload_json: { id: "i-1" },
            status_code: null,
            response_body: null,
            error_message: null,
            attempt_number: 1,
            next_retry_at: null,
            delivery_status: "failed",
            created_at: "2026-08-20T20:34:11Z",
            ...overrides,
          },
        ],
        next_cursor: null,
        has_more: false,
      }),
    ),
  );
}

function renderLogs(isActive = true) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <WebhookDeliveryLogs webhookId="wh-1" isActive={isActive} />
    </QueryClientProvider>,
  );
}

describe("WebhookDeliveryLogs", () => {
  it("calls the target's own reply a reply, not our error", async () => {
    // A 405 with an HTML page used to render under "Error" in full — sending
    // whoever looked for the cause into someone else's page template.
    mockDelivery({ status_code: 405, error_message: HTML_PAGE });
    renderLogs();

    // The event type is server data, not a catalogue key.
    // not-an-i18n-key
    fireEvent.click(await screen.findByText(/^item\.created$/));

    expect(screen.getByText("Response from the target")).toBeInTheDocument();
    expect(screen.queryByText("Error")).not.toBeInTheDocument();
    expect(screen.getByText("shortened")).toBeInTheDocument();
    expect(screen.queryByText(HTML_PAGE)).not.toBeInTheDocument();
  });

  it("still calls our own failure an error", async () => {
    // No status code means the request never got an answer — a timeout, a
    // refused connection: that one is ours.
    mockDelivery({
      status_code: null,
      error_message: "Connection timed out",
    });
    renderLogs();

    // The event type is server data, not a catalogue key.
    // not-an-i18n-key
    fireEvent.click(await screen.findByText(/^item\.created$/));

    expect(screen.getByText("Error")).toBeInTheDocument();
    expect(screen.getByText("Connection timed out")).toBeInTheDocument();
    expect(
      screen.queryByText("Response from the target"),
    ).not.toBeInTheDocument();
  });
  it("announces that a row opens, and that it has", async () => {
    // The only sign a row was clickable was that it is a button; the state
    // it toggles is now spoken too, for readers who do not see the chevron.
    mockDelivery({ status_code: 500, error_message: "boom" });
    renderLogs();

    const row = await screen.findByRole("button", { expanded: false });
    fireEvent.click(row);

    expect(screen.getByRole("button", { expanded: true })).toBe(row);
  });

  it("tells two retries in the same minute apart", async () => {
    // Four attempts all read "20.08.2026, 20:34" — the log is read for the
    // order between them, and the format hid it. The assertion pins the
    // seconds (":34:11"), not the hour, so it holds in any host timezone.
    mockDelivery({
      status_code: 500,
      error_message: "boom",
      created_at: "2026-08-20T20:34:11Z",
    });
    renderLogs();

    expect(await screen.findByText(/:34:11/)).toBeInTheDocument();
  });

  it("dates the row with the attempt that answered, not the enqueue", async () => {
    // A retry answering 54 seconds after the enqueue used to wear the
    // enqueue time — a success stamped before the event it describes.
    mockDelivery({
      status_code: 200,
      error_message: null,
      created_at: "2026-08-20T20:05:10Z",
      last_attempt_at: "2026-08-20T20:06:04Z",
    });
    renderLogs();

    expect(await screen.findByText(/:06:04/)).toBeInTheDocument();
    expect(screen.queryByText(/:05:10/)).not.toBeInTheDocument();
  });

  it("shows the delivery id the receiver saw", async () => {
    // Matching a history row against the receiver's log needs the id the
    // receiver printed, not the row's database key.
    mockDelivery({
      status_code: 500,
      error_message: "boom",
      delivery_id: "550e8400-e29b-41d4-a716-446655440000",
    });
    renderLogs();

    // The event type is server data, not a catalogue key.
    // not-an-i18n-key
    fireEvent.click(await screen.findByText(/^item\.created$/));

    expect(screen.getByText(/Delivery ID/)).toBeInTheDocument();
    expect(
      screen.getByText("550e8400-e29b-41d4-a716-446655440000"),
    ).toBeInTheDocument();
  });

  it("signs an abandonment as ours, with the reason and no borrowed status", async () => {
    // The breaker cut the endpoint after a 500; the row used to keep that
    // 500 and read "Response from the target: Webhook disabled or deleted"
    // — sending the reader to fix the receiver when the breaker lives here.
    mockDelivery({
      status_code: null,
      response_body: null,
      error_message: null,
      abandon_reason: "circuit_breaker",
      delivery_status: "failed",
    });
    renderLogs();

    // The event type is server data, not a catalogue key.
    // not-an-i18n-key
    fireEvent.click(await screen.findByText(/^item\.created$/));

    expect(
      screen.getByText("Abandoned by Inventari — the target never answered"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "The circuit breaker cut this endpoint off after repeated failures.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Response from the target"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/HTTP \d+/)).not.toBeInTheDocument();
  });

  it("offers a retry instead of saying there are no deliveries when the log failed", async () => {
    server.use(
      http.get("*/webhooks/endpoints/:id/deliveries", () =>
        HttpResponse.json({ detail: "down" }, { status: 500 }),
      ),
    );
    renderLogs();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText(/no deliveries/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /try again/i })).toBeVisible();
  });
});

describe("WebhookDeliveryLogs — paging and failure", () => {
  function pagedHandler() {
    const asked: (string | null)[] = [];
    server.use(
      http.get("*/webhooks/endpoints/:id/deliveries", ({ request }) => {
        const cursor = new URL(request.url).searchParams.get("cursor");
        asked.push(cursor);
        const second = cursor === "c2";
        return HttpResponse.json({
          items: [
            {
              id: second ? "d-2" : "d-1",
              event_type: second ? "item.updated" : "item.created",
              payload_json: {},
              status_code: 200,
              response_body: null,
              error_message: null,
              attempt_number: 1,
              next_retry_at: null,
              delivery_status: "success",
              created_at: "2026-08-20T20:34:11Z",
            },
          ],
          next_cursor: second ? null : "c2",
          has_more: !second,
        });
      }),
    );
    return asked;
  }

  it("walks forward and back through the pages without losing its place", async () => {
    // Going back must reuse the cursor that produced the previous page; a
    // reader who pressed Previous landed on the first page every time.
    const asked = pagedHandler();
    renderLogs();

    expect(await screen.findByText(/^item\.created$/)).toBeInTheDocument();
    const next = screen.getByRole("button", { name: /next/i });
    const prev = screen.getByRole("button", { name: /previous|prev/i });
    expect(prev).toBeDisabled();

    fireEvent.click(next);
    expect(await screen.findByText(/^item\.updated$/)).toBeInTheDocument();
    expect(screen.getByText("Page 2")).toBeInTheDocument();
    expect(next).toBeDisabled();

    fireEvent.click(prev);
    expect(await screen.findByText(/^item\.created$/)).toBeInTheDocument();
    expect(screen.getByText("Page 1")).toBeInTheDocument();
    expect(asked[0]).toBeNull();
    expect(asked).toContain("c2");
  });

  it("offers a retry when the log could not be read, and shows it afterwards", async () => {
    let attempts = 0;
    server.use(
      http.get("*/webhooks/endpoints/:id/deliveries", () => {
        attempts += 1;
        return attempts === 1
          ? HttpResponse.json({ detail: "boom" }, { status: 500 })
          : HttpResponse.json({
              items: [],
              next_cursor: null,
              has_more: false,
            });
      }),
    );
    renderLogs();
    fireEvent.click(await screen.findByRole("button", { name: /try again/i }));
    expect(await screen.findByText("No deliveries yet")).toBeInTheDocument();
    expect(attempts).toBe(2);
  });

  it("says that events are skipped, not queued, while the endpoint is off", async () => {
    mockDelivery({});
    renderLogs(false);

    expect(
      await screen.findByText(/not delivered, queued or logged/i),
    ).toBeInTheDocument();
  });

  it("stays quiet about skipped events while the endpoint is on", async () => {
    mockDelivery({});
    renderLogs(true);

    await screen.findByText(/^item\.created$/);
    expect(screen.queryByText(/not delivered, queued or logged/i)).toBeNull();
  });
});
