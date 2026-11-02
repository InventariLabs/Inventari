import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";

import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { equipmentApi } from "@/modules/equipment/api/equipment";

import ImportEquipmentModal from "../components/ImportEquipmentModal";
import { AssignmentsTab } from "../components/AssetAssignmentsTab";
import type { Item } from "@/types";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    loading: vi.fn(),
    warning: vi.fn(),
  },
}));

vi.mock("@/contexts/ModulesContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ModulesContext")>()),
  useModules: () => ({
    enabledModules: ["equipment"],
    isModuleEnabled: () => true,
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

/**
 * A request that fails without a word is worse than one that fails loudly.
 *
 * Both of these paths swallowed the rejection whole. The import modal had a
 * `finally` and no `catch`, so the spinner stopped, the step did not move and
 * the file stayed selected -- a screen indistinguishable from one nobody had
 * clicked. The pass pressed Analyze twice, collected two 500s, and was told
 * nothing either time.
 *
 * The protocol download was the module's only raw `useMutation`, carrying an
 * `onSuccess` and nothing else. It is also the only paper a checkout leaves
 * behind, so "no file appeared" is not a state anybody should have to guess at.
 */
function renderWith(ui: React.ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const ACCOUNT = ["equipment:read", "equipment:write", "items:read"];

const ANALYSIS = {
  headers: ["name"],
  total_rows: 1,
  preview_rows: [],
  suggested_mapping: { name: "name" },
};

/**
 * The analysis is a multipart POST. Under MSW in jsdom that request reaches
 * the handler but its response never returns to axios, so the await hangs and
 * neither branch of the try is ever taken. This change is about which branch
 * runs on a rejection, so the API call is the seam -- stubbing it exercises
 * exactly the code that was missing, without asking the transport to work.
 */
function analysisFails(status = 500) {
  const error = Object.assign(new Error("Request failed"), {
    isAxiosError: true,
    response: { status, data: null },
    config: {},
    toJSON: () => ({}),
  });
  return vi
    .spyOn(equipmentApi, "analyzeImport")
    .mockRejectedValue(error as unknown as Error);
}

function analysisSucceeds() {
  return vi.spyOn(equipmentApi, "analyzeImport").mockResolvedValue(ANALYSIS);
}

/** The file input is visually hidden, so drive its change event directly. */
function chooseFile(name: string) {
  const input = document.querySelector(
    'input[type="file"]',
  ) as HTMLInputElement;
  fireEvent.change(input, {
    target: { files: [new File(["name\nDell"], name, { type: "text/csv" })] },
  });
}

const ASSET = {
  id: "item-1",
  name: "Dell Latitude",
  quantity: 1,
  meta_data: { equipment: { status: "CHECKED_OUT" } },
} as unknown as Item;

const ASSIGNMENT = {
  id: "assignment-1",
  item_id: "item-1",
  assigned_to_name: "Anna",
  assigned_at: "2026-08-01T10:00:00Z",
  checked_in_at: null,
};

beforeEach(() => {
  window.URL.createObjectURL = vi.fn(() => "blob:protocol");
  window.URL.revokeObjectURL = vi.fn();
  server.resetHandlers();
  server.use(
    http.get("/api/v1/categories", () => HttpResponse.json(onePage([]))),
    http.get("/api/v1/locations", () => HttpResponse.json(onePage([]))),
    http.get("/api/v1/equipment/assignments/item/item-1", () =>
      HttpResponse.json(onePage([ASSIGNMENT])),
    ),
  );
  signInWith(ACCOUNT);
  vi.mocked(toast.error).mockClear();
});

afterEach(() => {
  signOut();
});

describe("Equipment import — a failed analysis says so", () => {
  it("shows the reason in the modal and leaves Analyze usable", async () => {
    analysisFails(400);
    renderWith(<ImportEquipmentModal onClose={vi.fn()} />);

    chooseFile("assets.csv");
    fireEvent.click(screen.getByRole("button", { name: /analyze/i }));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/could not read the file/i)).toBeInTheDocument();
    // The reader has to be able to try again without reopening the modal.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /analyze/i })).toBeEnabled(),
    );
  });

  it("blames the server, not the file, when the server failed", async () => {
    analysisFails(500);
    renderWith(<ImportEquipmentModal onClose={vi.fn()} />);

    chooseFile("assets.csv");
    fireEvent.click(screen.getByRole("button", { name: /analyze/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /server could not analyse/i,
    );
    expect(screen.queryByText(/could not read the file/i)).toBeNull();
  });

  it("moves to the mapping step and says nothing when the analysis works", async () => {
    analysisSucceeds();
    renderWith(<ImportEquipmentModal onClose={vi.fn()} />);

    chooseFile("assets.csv");
    fireEvent.click(screen.getByRole("button", { name: /analyze/i }));

    expect(await screen.findByText(/1 row found/i)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("drops a stale error when a different file is chosen", async () => {
    analysisFails();
    renderWith(<ImportEquipmentModal onClose={vi.fn()} />);

    chooseFile("first.csv");
    fireEvent.click(screen.getByRole("button", { name: /analyze/i }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();

    chooseFile("second.csv");

    await waitFor(() =>
      expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
    );
  });
});

const RETURNED_ASSIGNMENT = {
  id: "assignment-0",
  item_id: "item-1",
  assigned_to_name: "Bartek",
  assigned_at: "2026-07-01T10:00:00Z",
  checked_in_at: "2026-07-20T10:00:00Z",
};

function protocolHtmlIsServed() {
  server.use(
    http.get("/api/v1/equipment/assignments/:id/protocol/html", () =>
      HttpResponse.text("<p>Handover</p>"),
    ),
  );
}

async function openTheProtocol(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: /^protocol$/i }));
  return user.click(
    await screen.findByRole("button", { name: /download pdf/i }),
  );
}

describe("Equipment protocol — a failed download says so", () => {
  it("reports the failure instead of doing nothing", async () => {
    protocolHtmlIsServed();
    server.use(
      http.get(
        "/api/v1/equipment/assignments/assignment-1/protocol/pdf",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderWith(
      <AssignmentsTab item={ASSET} onCheckout={vi.fn()} onCheckin={vi.fn()} />,
    );

    await openTheProtocol(user);

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(vi.mocked(toast.error).mock.calls[0][0]).toMatch(
      /could not download the protocol/i,
    );
  });

  it("says nothing when the download succeeds", async () => {
    protocolHtmlIsServed();
    server.use(
      http.get(
        "/api/v1/equipment/assignments/assignment-1/protocol/pdf",
        () => new HttpResponse(new Blob(["%PDF-1.4"])),
      ),
    );
    // jsdom implements no navigation — the download anchor's click would
    // land on "Not implemented: navigation" after the test ends.
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    const user = userEvent.setup();
    renderWith(
      <AssignmentsTab item={ASSET} onCheckout={vi.fn()} onCheckin={vi.fn()} />,
    );

    await openTheProtocol(user);

    await waitFor(() => expect(toast.error).not.toHaveBeenCalled());
    clickSpy.mockRestore();
  });
});

describe("Equipment protocol — the returned assignment has a door too", () => {
  /**
   * The backend picks the CHECKIN template by `checked_in_at`
   * (`protocol_service.render_protocol_html`), and the row used to hide its
   * protocol controls on exactly that condition — so the return protocol, a
   * document an admin can edit under Templates, had no way in from the
   * interface. Reverting the row to the old `checked_in_at ? badges :
   * buttons` shape fails this one.
   */
  it("offers the protocol on a row that was already checked in", async () => {
    server.use(
      http.get("/api/v1/equipment/assignments/item/item-1", () =>
        HttpResponse.json(onePage([RETURNED_ASSIGNMENT])),
      ),
    );
    renderWith(
      <AssignmentsTab item={ASSET} onCheckout={vi.fn()} onCheckin={vi.fn()} />,
    );

    expect(
      await screen.findByRole("button", { name: /^protocol$/i }),
    ).toBeInTheDocument();
  });
});
