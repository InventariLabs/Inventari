import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useState } from "react";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import WebhooksPage from "./WebhooksPage";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";

// Mock react-i18next
// Mock LoadingSpinner
vi.mock("../../../components/LoadingSpinner", () => ({
  default: () => <div data-testid="loading-spinner">Loading…</div>,
}));

// Mock authStore — tests cover admin functionality, so default to admin user.
// The mock supports both useAuthStore() and useAuthStore((s) => s.x) call shapes
// so hooks like useHasPermission (which use the selector form) get the user slice.
const mockAuthState = {
  user: { role: "admin", is_superuser: false },
  isAuthenticated: true,
  isLoading: false,
};
vi.mock("@/store/authStore", () => ({
  useAuthStore: (selector?: (s: typeof mockAuthState) => unknown) =>
    selector ? selector(mockAuthState) : mockAuthState,
}));

import * as modulesCtx from "@/contexts/ModulesContext";
import { onePage } from "@/test/mocks/page";
import { toast } from "sonner";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

beforeEach(() => {
  vi.spyOn(modulesCtx, "useModules").mockReturnValue({
    enabledModules: ["webhooks"],
    isModuleEnabled: (name: string) => name === "webhooks",
    isLoading: false,
    refreshModules: vi.fn(),
    focusModule: null,
    hiddenModules: [],
  });
});

const createClient = () =>
  new QueryClient({ defaultOptions: { queries: { retry: false } } });

function ShellWrapper({ children }: { children: React.ReactNode }) {
  const [headerData, setHeaderData] = useState<{
    title?: string;
    subtitle?: string;
    actions?: React.ReactNode;
  }>({});
  return (
    <PageHeaderContext.Provider
      value={{ data: headerData, setHeader: setHeaderData }}
    >
      {headerData.title && <h1>{headerData.title}</h1>}
      {headerData.subtitle && <p>{headerData.subtitle}</p>}
      {headerData.actions}
      {children}
    </PageHeaderContext.Provider>
  );
}

const Wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider client={createClient()}>
    <BrowserRouter>
      <ShellWrapper>{children}</ShellWrapper>
    </BrowserRouter>
  </QueryClientProvider>
);

describe("WebhooksPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/webhooks/endpoints", () =>
        HttpResponse.json(onePage([])),
      ),
      http.get("/api/v1/webhooks/events", () => HttpResponse.json([])),
    );
  });

  it("renders the page title", async () => {
    render(<WebhooksPage />, { wrapper: Wrapper });
    expect(await screen.findByText("Webhooks")).toBeInTheDocument();
  });

  it("shows empty state when no webhooks", async () => {
    render(<WebhooksPage />, { wrapper: Wrapper });
    expect(
      await screen.findByText("No webhooks configured"),
    ).toBeInTheDocument();
  });

  it("shows Add webhook button for admin", async () => {
    render(<WebhooksPage />, { wrapper: Wrapper });
    const addButtons = await screen.findAllByText("Add webhook");
    expect(addButtons.length).toBeGreaterThan(0);
  });

  it("opens create modal on Add webhook click", async () => {
    render(<WebhooksPage />, { wrapper: Wrapper });
    const [firstAddBtn] = await screen.findAllByText("Add webhook");
    fireEvent.click(firstAddBtn);
    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    });
  });

  it("still offers a way to add one when the list is not empty", async () => {
    // The empty state used to hold the only reachable "Add webhook" button:
    // the other lives in the page header, and on the flat `/webhooks` route
    // nothing provided that header. Adding the first webhook therefore removed
    // the only way to add a second.
    server.use(
      http.get("/api/v1/webhooks/endpoints", () =>
        HttpResponse.json(
          onePage([
            {
              id: "abc-123",
              name: "Test Webhook",
              url: "https://example.com/hook",
              has_secret: false,
              http_method: "POST",
              event_types: ["item.created"],
              max_retries: 3,
              timeout_seconds: 10,
              is_active: true,
              last_triggered_at: null,
              last_status_code: null,
              consecutive_failures: 0,
              created_at: new Date().toISOString(),
            },
          ]),
        ),
      ),
    );

    render(<WebhooksPage />, { wrapper: Wrapper });
    await screen.findByText("Test Webhook");
    expect(
      screen.queryByText("No webhooks configured"),
    ).not.toBeInTheDocument();

    const addButton = screen.getByTestId("webhooks-add-btn");
    fireEvent.click(addButton);
    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    });
  });

  it("shows the reason a save was refused, and keeps the form open", async () => {
    // `await mutateAsync(...)` ran without a catch, so a 422 naming the
    // rejected address — and the switch that would allow it — reached nobody.
    server.use(
      http.post("/api/v1/webhooks/endpoints", () =>
        HttpResponse.json(
          {
            detail: {
              code: "WEBHOOK_URL_PRIVATE",
              field: "url",
              message:
                "This address is on a private network (192.168.1.50), which the server refuses to call.",
            },
          },
          { status: 422 },
        ),
      ),
      http.get("/api/v1/webhooks/events", () =>
        HttpResponse.json([
          { event_type: "item.created", description: "An item was created" },
        ]),
      ),
    );

    render(<WebhooksPage />, { wrapper: Wrapper });
    fireEvent.click(await screen.findByTestId("webhooks-add-btn"));

    const dialog = await screen.findByRole("dialog");
    fireEvent.change(screen.getByLabelText(/Name/i), {
      target: { value: "Home Assistant" },
    });
    fireEvent.change(screen.getByLabelText(/Target URL/i), {
      target: { value: "http://192.168.1.50:8123/hook" },
    });
    fireEvent.click(screen.getByLabelText(/item.created/i));
    fireEvent.click(screen.getByRole("button", { name: /Save/i }));

    expect(
      await screen.findByText(
        /This address is on a private network \(192\.168\.1\.50\)/,
      ),
    ).toBeInTheDocument();
    // The form is still there, with what was typed into it.
    expect(dialog).toBeInTheDocument();
    expect(screen.getByLabelText(/Target URL/i)).toHaveValue(
      "http://192.168.1.50:8123/hook",
    );
  });

  it("marks an event whose module is off instead of offering it as an equal", async () => {
    // The catalogue used to return all 42 events with no idea what this
    // organization runs — and 17 of them rendered as their own technical name.
    server.use(
      http.get("/api/v1/webhooks/events", () =>
        HttpResponse.json([
          {
            event_type: "item.created",
            description: "An item was added to inventory",
            source_module: null,
            available: true,
          },
          {
            event_type: "equipment.checkin",
            description: "A piece of equipment was returned",
            source_module: "equipment",
            available: false,
          },
        ]),
      ),
    );

    render(<WebhooksPage />, { wrapper: Wrapper });
    fireEvent.click(await screen.findByTestId("webhooks-add-btn"));
    await screen.findByRole("dialog");

    // Described, not just named.
    expect(
      await screen.findByText(/An item was added to inventory/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/A piece of equipment was returned/),
    ).toBeInTheDocument();
    // And the one this organization cannot emit says what it needs.
    expect(screen.getByText(/needs the .* module/)).toBeInTheDocument();
  });

  it("renders webhook cards when data is present", async () => {
    server.use(
      http.get("/api/v1/webhooks/endpoints", () =>
        HttpResponse.json(
          onePage([
            {
              id: "abc-123",
              name: "Test Webhook",
              url: "https://example.com/hook",
              has_secret: false,
              http_method: "POST",
              event_types: ["item.created"],
              max_retries: 3,
              timeout_seconds: 10,
              is_active: true,
              last_triggered_at: null,
              last_status_code: null,
              consecutive_failures: 0,
              created_at: new Date().toISOString(),
            },
          ]),
        ),
      ),
    );

    render(<WebhooksPage />, { wrapper: Wrapper });
    expect(await screen.findByText("Test Webhook")).toBeInTheDocument();
    // not-an-i18n-key: a webhook event type, rendered as data.
    expect(screen.getByText("item.created")).toBeInTheDocument();
  });

  it("names the status a test ping was refused with, not the page that came back", async () => {
    // The receiver's whole HTML body used to be the toast; its status was the
    // only useful part of it.
    server.use(
      http.get("/api/v1/webhooks/endpoints", () =>
        HttpResponse.json(
          onePage([
            {
              id: "abc-123",
              name: "Test Webhook",
              url: "https://example.com/hook",
              has_secret: false,
              http_method: "POST",
              event_types: ["item.created"],
              max_retries: 3,
              timeout_seconds: 10,
              is_active: true,
              last_triggered_at: null,
              last_status_code: null,
              consecutive_failures: 0,
              created_at: new Date().toISOString(),
            },
          ]),
        ),
      ),
      http.post("/api/v1/webhooks/endpoints/abc-123/test", () =>
        HttpResponse.json({
          success: false,
          status_code: 405,
          // Whatever the server says, a refusal with a status is shown by
          // its status: an older server sent the receiver's page here.
          error: "<!doctype html><html><title>Example Domain</title></html>",
          delivery_id: "d-1",
        }),
      ),
    );

    render(<WebhooksPage />, { wrapper: Wrapper });
    fireEvent.click(
      await screen.findByRole("button", { name: /Test Test Webhook/i }),
    );

    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1));
    const message = vi.mocked(toast.error).mock.calls[0][0] as string;
    expect(message).toMatch(/405/);
    expect(message).not.toMatch(/</);
  });

  it("says a passing test left a tripped endpoint off, and offers to turn it on", async () => {
    // The ping answered 200 and the card stayed "Inactive": the toast alone
    // read as if deliveries had resumed.
    const reactivated = vi.fn();
    server.use(
      http.get("/api/v1/webhooks/endpoints", () =>
        HttpResponse.json(
          onePage([
            {
              id: "abc-123",
              name: "Test Webhook",
              url: "https://example.com/hook",
              has_secret: false,
              http_method: "POST",
              event_types: ["item.created"],
              max_retries: 3,
              timeout_seconds: 10,
              is_active: false,
              last_triggered_at: null,
              last_status_code: null,
              consecutive_failures: 10,
              auto_disabled_at: new Date().toISOString(),
              created_at: new Date().toISOString(),
            },
          ]),
        ),
      ),
      http.post("/api/v1/webhooks/endpoints/abc-123/test", () =>
        HttpResponse.json({
          success: true,
          status_code: 200,
          error: null,
          delivery_id: "d-1",
        }),
      ),
      http.post("/api/v1/webhooks/endpoints/abc-123/reactivate", () => {
        reactivated();
        return HttpResponse.json({});
      }),
    );

    render(<WebhooksPage />, { wrapper: Wrapper });
    fireEvent.click(
      await screen.findByRole("button", { name: /Test Test Webhook/i }),
    );

    await waitFor(() => expect(toast.success).toHaveBeenCalledTimes(1));
    const [message, options] = vi.mocked(toast.success).mock.calls[0];
    expect(message).toMatch(/200.*still off/);
    const action = options?.action as unknown as { onClick: () => void };
    action.onClick();
    await waitFor(() => expect(reactivated).toHaveBeenCalledTimes(1));
  });
});

describe("WebhooksPage row actions", () => {
  const hook = {
    id: "abc-123",
    name: "Test Webhook",
    url: "https://example.com/hook",
    has_secret: false,
    http_method: "POST",
    event_types: ["item.created"],
    max_retries: 3,
    timeout_seconds: 10,
    is_active: true,
    last_triggered_at: null,
    last_status_code: null,
    consecutive_failures: 0,
    created_at: new Date().toISOString(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/webhooks/endpoints", () =>
        HttpResponse.json(onePage([hook])),
      ),
      http.get("/api/v1/webhooks/events", () =>
        HttpResponse.json([
          { event_type: "item.created", description: "An item was created" },
        ]),
      ),
      http.get("/api/v1/webhooks/endpoints/abc-123/deliveries", () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
    );
  });

  it("deletes only after the confirmation, and says so", async () => {
    // A delete that skipped the dialog would drop an integration and its
    // whole delivery history on a single mis-click.
    const deleted = vi.fn();
    server.use(
      http.delete("/api/v1/webhooks/endpoints/abc-123", () => {
        deleted();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    render(<WebhooksPage />, { wrapper: Wrapper });
    fireEvent.click(
      await screen.findByRole("button", { name: /Delete Test Webhook/i }),
    );
    const dialog = await screen.findByRole("alertdialog");
    expect(deleted).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(deleted).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(toast.success).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
  });

  it("leaves the webhook alone when the delete confirmation is cancelled", async () => {
    const deleted = vi.fn();
    server.use(
      http.delete("/api/v1/webhooks/endpoints/abc-123", () => {
        deleted();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    render(<WebhooksPage />, { wrapper: Wrapper });
    fireEvent.click(
      await screen.findByRole("button", { name: /Delete Test Webhook/i }),
    );
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
    expect(deleted).not.toHaveBeenCalled();
    expect(screen.getByText("Test Webhook")).toBeInTheDocument();
  });

  it("shows the server's reason when a delete is refused", async () => {
    server.use(
      http.delete("/api/v1/webhooks/endpoints/abc-123", () =>
        HttpResponse.json({ detail: "Not allowed right now" }, { status: 403 }),
      ),
    );
    render(<WebhooksPage />, { wrapper: Wrapper });
    fireEvent.click(
      await screen.findByRole("button", { name: /Delete Test Webhook/i }),
    );
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1));
    expect(toast.success).not.toHaveBeenCalled();
    expect(vi.mocked(toast.error).mock.calls[0][0]).toBe(
      "Not allowed right now",
    );
  });

  it("opens the edit form filled in and saves through PUT", async () => {
    // An edit that posted as a create would leave the old endpoint and add a
    // duplicate that delivers every event twice.
    let body: Record<string, unknown> | null = null;
    server.use(
      http.put("/api/v1/webhooks/endpoints/abc-123", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...hook, ...body });
      }),
    );
    render(<WebhooksPage />, { wrapper: Wrapper });
    fireEvent.click(
      await screen.findByRole("button", { name: /Edit Test Webhook/i }),
    );
    await screen.findByRole("dialog");
    const name = screen.getByLabelText(/Name/i);
    expect(name).toHaveValue("Test Webhook");
    fireEvent.change(name, { target: { value: "Renamed" } });
    fireEvent.click(screen.getByRole("button", { name: /Save/i }));

    await waitFor(() => expect(toast.success).toHaveBeenCalledTimes(1));
    expect(body).toMatchObject({ name: "Renamed" });
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("closes the create form with Cancel without saving anything", async () => {
    render(<WebhooksPage />, { wrapper: Wrapper });
    fireEvent.click(await screen.findByTestId("webhooks-add-btn"));
    await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: /Cancel/i }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("opens the delivery log of that webhook and closes it again", async () => {
    render(<WebhooksPage />, { wrapper: Wrapper });
    fireEvent.click(
      await screen.findByRole("button", {
        name: /Delivery logs Test Webhook/i,
      }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Test Webhook")).toBeInTheDocument();
    expect(await within(dialog).findByText("No deliveries yet")).toBeVisible();

    // Header cross and footer button both close it; use the footer one.
    const closers = within(dialog).getAllByRole("button", { name: "Close" });
    expect(closers).toHaveLength(2);
    fireEvent.click(closers[1]);
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("reports a passing test of a live endpoint with its status", async () => {
    server.use(
      http.post("/api/v1/webhooks/endpoints/abc-123/test", () =>
        HttpResponse.json({
          success: true,
          status_code: 204,
          error: null,
          delivery_id: "d-1",
        }),
      ),
    );
    render(<WebhooksPage />, { wrapper: Wrapper });
    fireEvent.click(
      await screen.findByRole("button", { name: /Test Test Webhook/i }),
    );
    await waitFor(() => expect(toast.success).toHaveBeenCalledTimes(1));
    expect(vi.mocked(toast.success).mock.calls[0][0]).toMatch(/204/);
    expect(vi.mocked(toast.success).mock.calls[0][1]).toBeUndefined();
  });

  it("gives the connection error when the receiver never answered", async () => {
    server.use(
      http.post("/api/v1/webhooks/endpoints/abc-123/test", () =>
        HttpResponse.json({
          success: false,
          status_code: null,
          error: "connection refused",
          delivery_id: "d-1",
        }),
      ),
    );
    render(<WebhooksPage />, { wrapper: Wrapper });
    fireEvent.click(
      await screen.findByRole("button", { name: /Test Test Webhook/i }),
    );
    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1));
    expect(vi.mocked(toast.error).mock.calls[0][0]).toMatch(
      /connection refused/,
    );
  });

  it("shows the API error when the test request itself fails", async () => {
    server.use(
      http.post("/api/v1/webhooks/endpoints/abc-123/test", () =>
        HttpResponse.json({ detail: "Webhooks are off" }, { status: 409 }),
      ),
    );
    render(<WebhooksPage />, { wrapper: Wrapper });
    fireEvent.click(
      await screen.findByRole("button", { name: /Test Test Webhook/i }),
    );
    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1));
    expect(vi.mocked(toast.error).mock.calls[0][0]).toBe("Webhooks are off");
  });

  it("reactivates from the card button and confirms; a refusal is reported", async () => {
    let refuse = false;
    server.use(
      http.get("/api/v1/webhooks/endpoints", () =>
        HttpResponse.json(
          onePage([
            {
              ...hook,
              is_active: false,
              auto_disabled_at: new Date().toISOString(),
              consecutive_failures: 10,
            },
          ]),
        ),
      ),
      http.post("/api/v1/webhooks/endpoints/abc-123/reactivate", () =>
        refuse
          ? HttpResponse.json({ detail: "Still failing" }, { status: 409 })
          : HttpResponse.json({}),
      ),
    );
    render(<WebhooksPage />, { wrapper: Wrapper });
    const button = await screen.findByRole("button", {
      name: /Reactivate Test Webhook/i,
    });
    fireEvent.click(button);
    await waitFor(() => expect(toast.success).toHaveBeenCalledTimes(1));

    refuse = true;
    fireEvent.click(button);
    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1));
    expect(vi.mocked(toast.error).mock.calls[0][0]).toBe("Still failing");
  });

  it("opens the create form from both Add buttons when there are no webhooks yet", async () => {
    // The empty state and the page header each carry their own button; one
    // wired to nothing would leave a first-time administrator stuck.
    server.use(
      http.get("/api/v1/webhooks/endpoints", () =>
        HttpResponse.json(onePage([])),
      ),
    );
    render(<WebhooksPage />, { wrapper: Wrapper });
    await screen.findByText("No webhooks configured");
    const buttons = screen.getAllByTestId("webhooks-add-btn");
    expect(buttons).toHaveLength(2);

    for (const button of buttons) {
      fireEvent.click(button);
      expect(await screen.findByRole("dialog")).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: /Cancel/i }));
      await waitFor(() =>
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
      );
    }
  });

  it("closes the form sheet from its header cross and from Escape", async () => {
    render(<WebhooksPage />, { wrapper: Wrapper });
    fireEvent.click(await screen.findByTestId("webhooks-add-btn"));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );

    fireEvent.click(screen.getByTestId("webhooks-add-btn"));
    await screen.findByRole("dialog");
    fireEvent.keyDown(document.body, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("closes the delivery log with Escape as well", async () => {
    render(<WebhooksPage />, { wrapper: Wrapper });
    fireEvent.click(
      await screen.findByRole("button", {
        name: /Delivery logs Test Webhook/i,
      }),
    );
    await screen.findByRole("dialog");
    fireEvent.keyDown(document.body, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("confirms a created webhook and closes the form", async () => {
    server.use(
      http.post("/api/v1/webhooks/endpoints", () =>
        HttpResponse.json(hook, { status: 201 }),
      ),
    );
    render(<WebhooksPage />, { wrapper: Wrapper });
    fireEvent.click(await screen.findByTestId("webhooks-add-btn"));
    await screen.findByRole("dialog");
    fireEvent.change(screen.getByLabelText(/Name/i), {
      target: { value: "Fresh" },
    });
    fireEvent.change(screen.getByLabelText(/Target URL/i), {
      target: { value: "https://example.com/fresh" },
    });
    fireEvent.click(await screen.findByLabelText(/item.created/i));
    fireEvent.click(screen.getByRole("button", { name: /Save/i }));

    await waitFor(() => expect(toast.success).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });
});
