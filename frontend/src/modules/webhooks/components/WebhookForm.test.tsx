import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AxiosError, AxiosHeaders } from "axios";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import * as modulesCtx from "@/contexts/ModulesContext";
import WebhookForm from "./WebhookForm";
import type { WebhookEndpoint } from "@/modules/webhooks/types/webhooks";

//: An endpoint seeded before item.consumed was cut from the catalogue: the
//: row still carries the name, the catalogue no longer lists it, and the
//: rows are not migrated.
const LEGACY_ENDPOINT: WebhookEndpoint = {
  id: "wh-legacy",
  name: "Legacy hook",
  url: "https://example.test/hook",
  has_secret: false,
  http_method: "POST",
  event_types: ["item.created", "item.consumed"],
  max_retries: 3,
  retry_backoff_seconds: 60,
  timeout_seconds: 10,
  is_active: true,
  last_triggered_at: null,
  last_status_code: null,
  consecutive_failures: 0,
  auto_disabled_at: null,
  events_all_module_disabled: false,
  events_unknown: true,
  created_at: "2026-08-01T10:00:00Z",
  updated_at: "2026-08-01T10:00:00Z",
};

function renderForm(
  webhook?: WebhookEndpoint,
  onSave = vi.fn(),
  onCancel = vi.fn(),
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <WebhookForm webhook={webhook} onSave={onSave} onCancel={onCancel} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.spyOn(modulesCtx, "useModules").mockReturnValue({
    enabledModules: ["webhooks"],
    isModuleEnabled: (name: string) => name === "webhooks",
    isLoading: false,
    refreshModules: vi.fn(),
    focusModule: null,
    hiddenModules: [],
  });
  server.use(
    http.get("*/webhooks/events", () =>
      HttpResponse.json([
        {
          event_type: "item.created",
          description: "An item was created",
          available: true,
          source_module: null,
        },
      ]),
    ),
  );
});

describe("WebhookForm — every control says what it is", () => {
  it("names all five fields for a screen reader", async () => {
    renderForm();

    // The secret, the retry count and the timeout carried a bare <label>
    // bound to nothing: on screen, but absent from the accessibility tree.
    expect(await screen.findByLabelText(/name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/target url/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/secret/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/max retries/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/timeout/i)).toBeInTheDocument();
  });

  it("names the active switch and the method group", async () => {
    renderForm();

    // A <label> wrapping a <div role="checkbox"> names nothing.
    const active = await screen.findByRole("switch");
    expect(active).toHaveAccessibleName("Active");

    expect(
      screen.getByRole("radiogroup", { name: /http method/i }),
    ).toBeInTheDocument();
  });

  it("keeps the actions out of the scrolling area", async () => {
    renderForm();

    // With forty-two events on offer the form is taller than a 900px window;
    // Save used to scroll below the bottom edge of the dialog.
    const save = await screen.findByRole("button", { name: /save/i });
    const scroller = save.closest(".overflow-y-auto");
    expect(scroller).toBeNull();
  });

  it("counts the chosen events in the reader's language", async () => {
    renderForm();

    // `({selectedEvents.length} selected)` was English whatever the locale.
    const checkbox = await screen.findByRole("checkbox");
    fireEvent.click(checkbox);

    expect(await screen.findByText("(1 selected)")).toBeInTheDocument();
  });

  it("keeps a withdrawn subscription visible and removable", async () => {
    // The row held item.consumed, the catalogue no longer lists it, and the
    // form rendered the catalogue alone — so the field showed "1 selected"
    // with nothing ticked beside it and every Save answered 422 with the
    // name it refused. Rendering the withdrawn name is what makes the
    // subscription removable.
    const onSave = vi.fn();
    renderForm(LEGACY_ENDPOINT, onSave);

    expect(
      await screen.findByText("No longer in the catalogue"),
    ).toBeInTheDocument();
    const withdrawn = await screen.findByRole("checkbox", {
      name: /item\.consumed/,
    });
    expect(withdrawn).toBeChecked();

    fireEvent.click(withdrawn);
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ event_types: ["item.created"] }),
    );
  });
});

describe("WebhookForm — what the Save button sends", () => {
  it("sends every field the reader changed, with numbers as numbers", async () => {
    // The retry and timeout inputs hand back strings; a payload that kept
    // "5" instead of 5 is a 422 the reader cannot explain.
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderForm(undefined, onSave);

    fireEvent.change(await screen.findByLabelText(/name/i), {
      target: { value: "Slack" },
    });
    fireEvent.change(screen.getByLabelText(/target url/i), {
      target: { value: "https://example.test/in" },
    });
    fireEvent.change(screen.getByLabelText(/secret/i), {
      target: { value: "s3cret" },
    });
    fireEvent.click(screen.getByRole("radio", { name: "PUT" }));
    fireEvent.change(screen.getByLabelText(/max retries/i), {
      target: { value: "5" },
    });
    fireEvent.change(screen.getByLabelText(/timeout/i), {
      target: { value: "20" },
    });
    fireEvent.click(await screen.findByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledWith({
      name: "Slack",
      url: "https://example.test/in",
      http_method: "PUT",
      event_types: ["item.created"],
      max_retries: 5,
      timeout_seconds: 20,
      is_active: true,
      secret: "s3cret",
    });
  });

  it("leaves the secret out when the field was not touched", async () => {
    // Sending an empty secret on edit would wipe the one already stored.
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderForm({ ...LEGACY_ENDPOINT, has_secret: true }, onSave);
    await screen.findByText("No longer in the catalogue");
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0]).not.toHaveProperty("secret");
  });

  it("cannot be saved without a subscribed event", async () => {
    renderForm();
    await screen.findByRole("checkbox");
    expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();
  });

  it("hands Cancel to the page and saves nothing", async () => {
    const onSave = vi.fn();
    const onCancel = vi.fn();
    renderForm(undefined, onSave, onCancel);
    fireEvent.click(await screen.findByRole("button", { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onSave).not.toHaveBeenCalled();
  });
});

describe("WebhookForm — the Active switch", () => {
  it("flips on click and on Space or Enter, and nothing else", async () => {
    // A switch that answered only the mouse left keyboard users stuck on
    // whatever the endpoint was saved with.
    renderForm();
    const active = await screen.findByRole("switch");
    expect(active).toHaveAttribute("aria-checked", "true");

    fireEvent.click(active);
    expect(active).toHaveAttribute("aria-checked", "false");
    fireEvent.keyDown(active, { key: " " });
    expect(active).toHaveAttribute("aria-checked", "true");
    fireEvent.keyDown(active, { key: "Enter" });
    expect(active).toHaveAttribute("aria-checked", "false");
    fireEvent.keyDown(active, { key: "a" });
    expect(active).toHaveAttribute("aria-checked", "false");
  });

  it("is saved off when the reader switched it off", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderForm(undefined, onSave);
    fireEvent.change(await screen.findByLabelText(/name/i), {
      target: { value: "Slack" },
    });
    fireEvent.change(screen.getByLabelText(/target url/i), {
      target: { value: "https://example.test/in" },
    });
    fireEvent.click(await screen.findByRole("switch"));
    fireEvent.click(await screen.findByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0]).toMatchObject({ is_active: false });
  });
});

describe("WebhookForm — warnings and failures", () => {
  it("warns about clear text only for an http address", async () => {
    renderForm();
    const url = await screen.findByLabelText(/target url/i);
    expect(screen.queryByText(/clear text/)).not.toBeInTheDocument();
    fireEvent.change(url, { target: { value: "http://example.test/in" } });
    expect(screen.getByText(/clear text/)).toBeInTheDocument();
    fireEvent.change(url, { target: { value: "https://example.test/in" } });
    expect(screen.queryByText(/clear text/)).not.toBeInTheDocument();
  });

  it("warns about a missing secret, and stops once one is typed", async () => {
    renderForm();
    const secret = await screen.findByLabelText(/secret/i);
    expect(screen.getByText(/cannot tell your payloads/)).toBeInTheDocument();
    fireEvent.change(secret, { target: { value: "x" } });
    expect(
      screen.queryByText(/cannot tell your payloads/),
    ).not.toBeInTheDocument();
  });

  it("offers a retry when the event catalogue did not arrive, and recovers", async () => {
    // "No event types" would send the reader to an administrator; the real
    // cause is a failed request that one more try fixes.
    let attempts = 0;
    server.use(
      http.get("*/webhooks/events", () => {
        attempts += 1;
        return attempts === 1
          ? HttpResponse.json({ detail: "boom" }, { status: 500 })
          : HttpResponse.json([
              {
                event_type: "item.created",
                description: "An item was created",
                available: true,
                source_module: null,
              },
            ]);
      }),
    );
    renderForm();
    fireEvent.click(await screen.findByRole("button", { name: /try again/i }));
    expect(await screen.findByRole("checkbox")).toBeInTheDocument();
    expect(attempts).toBe(2);
  });

  it("shows a refusal that is not about the address as an alert", async () => {
    const onSave = vi.fn().mockRejectedValue(
      new AxiosError(
        "Request failed",
        "ERR_BAD_REQUEST",
        undefined,
        undefined,
        {
          status: 409,
          statusText: "Conflict",
          headers: {},
          config: { headers: new AxiosHeaders() },
          data: { detail: "Quota reached" },
        },
      ),
    );
    renderForm(undefined, onSave);
    fireEvent.change(await screen.findByLabelText(/name/i), {
      target: { value: "Slack" },
    });
    fireEvent.change(screen.getByLabelText(/target url/i), {
      target: { value: "https://example.test/in" },
    });
    fireEvent.click(await screen.findByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Quota reached");
  });
});
