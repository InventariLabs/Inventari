import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { server } from "@/test/mocks/server";
import { SendToPrinterButton } from "./SendToPrinterButton";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

let enabledModules = ["printing"];
vi.mock("@/contexts/ModulesContext", () => ({
  useEnabledModulesOptional: () => enabledModules,
}));

const agent = (id: string, name: string, online = true) => ({
  id,
  name,
  printer_type: "brother-p710bt",
  last_seen_at: "2026-10-06T21:00:00Z",
  online,
});

const job = {
  id: "job-1",
  agent_id: "a-1",
  status: "queued",
  count: 2,
  short_codes: ["PRN-0001", "PRN-0002"],
  width_mm: 50,
  height_mm: 24,
  attempts: 0,
  error: null,
  created_at: "2026-10-06T21:00:00Z",
  finished_at: null,
};

function renderButton(
  props: Partial<Parameters<typeof SendToPrinterButton>[0]> = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <SendToPrinterButton target={{ labelIds: ["l-1", "l-2"] }} {...props} />
    </QueryClientProvider>,
  );
}

describe("SendToPrinterButton", () => {
  let sent: unknown[];

  beforeEach(() => {
    enabledModules = ["printing"];
    sent = [];
    server.use(
      http.post("/api/v1/printing/jobs", async ({ request }) => {
        sent.push(await request.json());
        return HttpResponse.json(job, { status: 201 });
      }),
    );
  });

  it("is absent while no printer has announced itself", async () => {
    server.use(
      http.get("/api/v1/printing/agents", () => HttpResponse.json(onePage([]))),
    );

    const { container } = renderButton();

    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("asks nothing of the server where the printing module is off", async () => {
    enabledModules = ["items"];
    const asked = vi.fn();
    server.use(
      http.get("/api/v1/printing/agents", () => {
        asked();
        return HttpResponse.json(onePage([agent("a-1", "office")]));
      }),
    );

    const { container } = renderButton();

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(asked).not.toHaveBeenCalled();
    expect(container).toBeEmptyDOMElement();
  });

  it("sends the chosen labels straight to the only printer", async () => {
    server.use(
      http.get("/api/v1/printing/agents", () =>
        HttpResponse.json(onePage([agent("a-1", "office")])),
      ),
    );
    const onSent = vi.fn();
    renderButton({
      onSent,
      options: { caption: "Spices", copies: 2 },
    });

    await userEvent.click(
      await screen.findByRole("button", { name: /send to printer/i }),
    );

    await waitFor(() => expect(onSent).toHaveBeenCalled());
    expect(sent).toEqual([
      {
        label_ids: ["l-1", "l-2"],
        agent_id: "a-1",
        caption: "Spices",
        qr_only: false,
        show_code: false,
        copies: 2,
        // No preview on this screen: the job takes the default label size,
        // since a printer has none of its own.
        width_mm: 50,
        height_mm: 24,
      },
    ]);
  });

  it("sends the size a preview chose rather than the default", async () => {
    server.use(
      http.get("/api/v1/printing/agents", () =>
        HttpResponse.json(onePage([agent("a-1", "office")])),
      ),
    );
    renderButton({ options: { width: 30, height: 30 } });

    await userEvent.click(
      await screen.findByRole("button", { name: /send to printer/i }),
    );

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({ width_mm: 30, height_mm: 30 });
  });

  it("asks which printer when there are several", async () => {
    server.use(
      http.get("/api/v1/printing/agents", () =>
        HttpResponse.json(
          onePage([agent("a-1", "office"), agent("a-2", "garage", false)]),
        ),
      ),
    );
    renderButton();

    await userEvent.click(
      await screen.findByRole("button", { name: /send to printer/i }),
    );
    expect(sent).toEqual([]);
    await userEvent.click(
      await screen.findByRole("button", { name: /garage/i }),
    );

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({ agent_id: "a-2" });
  });

  it("cannot be pressed while nothing is chosen", async () => {
    server.use(
      http.get("/api/v1/printing/agents", () =>
        HttpResponse.json(onePage([agent("a-1", "office")])),
      ),
    );

    renderButton({ target: null });

    expect(
      await screen.findByRole("button", { name: /send to printer/i }),
    ).toBeDisabled();
  });
});
