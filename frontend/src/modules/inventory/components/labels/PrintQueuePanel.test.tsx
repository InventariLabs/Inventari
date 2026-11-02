import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { server } from "@/test/mocks/server";
import { PrintQueuePanel } from "./PrintQueuePanel";
import { onePage } from "@/test/mocks/page";
import { toast } from "sonner";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

let enabledModules = ["printing", "api_keys"];
vi.mock("@/contexts/ModulesContext", () => ({
  useEnabledModulesOptional: () => enabledModules,
}));

const office = {
  id: "a-1",
  name: "office",
  printer_type: "brother-p710bt",
  last_seen_at: "2026-10-06T21:00:00Z",
  online: true,
};

const failed = {
  id: "job-1",
  agent_id: "a-1",
  status: "failed",
  count: 7,
  short_codes: ["PRN-0001", "PRN-0002", "PRN-0003", "PRN-0004", "PRN-0005"],
  width_mm: 50,
  height_mm: 24,
  attempts: 1,
  error: "Print command failed (exit 3): tape jammed",
  created_at: "2026-10-06T21:00:00Z",
  finished_at: "2026-10-06T21:00:05Z",
};

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <PrintQueuePanel />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PrintQueuePanel", () => {
  beforeEach(() => {
    enabledModules = ["printing", "api_keys"];
    server.use(
      http.get("/api/v1/printing/jobs", () =>
        HttpResponse.json(onePage([failed])),
      ),
    );
  });

  it("says how to connect a printer before any has started", async () => {
    server.use(
      http.get("/api/v1/printing/agents", () => HttpResponse.json(onePage([]))),
    );

    renderPanel();

    expect(
      await screen.findByText(/no printer is connected yet/i),
    ).toBeInTheDocument();
    // The setup is a page to read, not a command to type.
    expect(screen.queryByText(/agent\.py/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /set up the print agent/i }),
    ).toHaveAttribute("href", expect.stringContaining("print-agent"));
    // The first step works inside the app: the key page is one click away.
    expect(
      screen.getByRole("link", { name: /create a key for the agent/i }),
    ).toHaveAttribute("href", "/settings/api-keys");
  });

  it("leaves out the key page when the API keys module is off", async () => {
    enabledModules = ["printing"];
    server.use(
      http.get("/api/v1/printing/agents", () => HttpResponse.json(onePage([]))),
    );

    renderPanel();

    expect(
      await screen.findByText(/no printer is connected yet/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /create a key for the agent/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /set up the print agent/i }),
    ).toBeInTheDocument();
  });

  it("says the printers could not be read rather than that there are none", async () => {
    server.use(
      http.get("/api/v1/printing/agents", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    renderPanel();

    await waitFor(() =>
      expect(screen.getByTestId("print-queue-panel")).toBeInTheDocument(),
    );
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.queryByText(/no printer is connected yet/i),
    ).not.toBeInTheDocument();
  });

  it("shows each printer online or not, and no size of its own", async () => {
    server.use(
      http.get("/api/v1/printing/agents", () =>
        HttpResponse.json(
          onePage([
            office,
            { ...office, id: "a-2", name: "garage", online: false },
          ]),
        ),
      ),
    );

    renderPanel();

    const rows = await screen.findAllByTestId("print-agent-row");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("online")).toBeInTheDocument();
    // A printer has no media or size: the label's size is the job's.
    expect(within(rows[0]).queryByText(/mm/)).not.toBeInTheDocument();
    expect(
      within(rows[0]).queryByRole("button", { name: /media and size/i }),
    ).not.toBeInTheDocument();
    expect(within(rows[1]).getByText("offline")).toBeInTheDocument();
    expect(within(rows[1]).getByText(/last seen/i)).toBeInTheDocument();
  });

  it("says when a printer could only print a label smaller than its size", async () => {
    server.use(
      http.get("/api/v1/printing/agents", () =>
        HttpResponse.json(onePage([office])),
      ),
      http.get("/api/v1/printing/jobs", () =>
        HttpResponse.json(
          onePage([
            { ...failed, status: "printed", error: null, scale: 0.753 },
          ]),
        ),
      ),
    );

    renderPanel();

    const row = await screen.findByTestId("print-job-row");
    expect(
      within(row).getByText(/printed at 75% of its size/i),
    ).toBeInTheDocument();
  });

  // A job keeps the size it was sent with to the last digit, and a width
  // typed as 50.06 can reach it as the float the browser held.
  it("writes a job's size as a person would, not as the float it is", async () => {
    server.use(
      http.get("/api/v1/printing/agents", () =>
        HttpResponse.json(onePage([office])),
      ),
      http.get("/api/v1/printing/jobs", () =>
        HttpResponse.json(
          onePage([{ ...failed, width_mm: 50.060001373291016 }]),
        ),
      ),
    );

    renderPanel();

    const row = await screen.findByTestId("print-job-row");
    expect(within(row).getByText(/50\.06×24 mm/)).toBeInTheDocument();
  });

  it("names a failed job's labels and reason, and sends it again", async () => {
    let retried = 0;
    server.use(
      http.get("/api/v1/printing/agents", () =>
        HttpResponse.json(onePage([office])),
      ),
      http.post("/api/v1/printing/jobs/job-1/retry", () => {
        retried += 1;
        return HttpResponse.json({ ...failed, status: "queued", error: null });
      }),
    );

    renderPanel();

    const row = await screen.findByTestId("print-job-row");
    expect(within(row).getByText("Failed")).toBeInTheDocument();
    expect(within(row).getByText(/PRN-0001, PRN-0002/)).toBeInTheDocument();
    expect(within(row).getByText(/and 2 more/)).toBeInTheDocument();
    expect(within(row).getByText(/50×24 mm/)).toBeInTheDocument();
    expect(within(row).getByText(/tape jammed/)).toBeInTheDocument();

    await userEvent.click(
      within(row).getByRole("button", { name: /send again/i }),
    );

    await waitFor(() => expect(retried).toBe(1));
  });

  it("asks for the printers again from the notice, and lists them when they answer", async () => {
    let asked = 0;
    let failing = true;
    server.use(
      http.get("/api/v1/printing/agents", () => {
        asked += 1;
        return failing
          ? new HttpResponse(null, { status: 500 })
          : HttpResponse.json(onePage([office]));
      }),
    );
    renderPanel();
    const notice = await screen.findByRole("alert");
    const before = asked;

    failing = false;
    await userEvent.click(
      within(notice).getByRole("button", { name: /try again/i }),
    );

    expect(await screen.findAllByTestId("print-agent-row")).toHaveLength(1);
    expect(asked).toBeGreaterThan(before);
  });

  it("asks for the print jobs again from their own notice", async () => {
    let asked = 0;
    let failing = true;
    server.use(
      http.get("/api/v1/printing/agents", () =>
        HttpResponse.json(onePage([office])),
      ),
      http.get("/api/v1/printing/jobs", () => {
        asked += 1;
        return failing
          ? new HttpResponse(null, { status: 500 })
          : HttpResponse.json(onePage([failed]));
      }),
    );
    renderPanel();
    const notice = await screen.findByRole("alert");
    const before = asked;

    failing = false;
    await userEvent.click(
      within(notice).getByRole("button", { name: /try again/i }),
    );

    expect(await screen.findByTestId("print-job-row")).toBeInTheDocument();
    expect(asked).toBeGreaterThan(before);
  });

  it("says so when sending a failed job again fails too", async () => {
    server.use(
      http.get("/api/v1/printing/agents", () =>
        HttpResponse.json(onePage([office])),
      ),
      http.post(
        "/api/v1/printing/jobs/job-1/retry",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    vi.mocked(toast.error).mockClear();
    vi.mocked(toast.success).mockClear();
    renderPanel();

    await userEvent.click(
      await screen.findByRole("button", { name: /send again/i }),
    );

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(toast.success).not.toHaveBeenCalled();
  });
});
