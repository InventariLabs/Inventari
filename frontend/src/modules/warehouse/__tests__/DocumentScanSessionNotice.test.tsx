import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryWrapper } from "@/test/queryWrapper";
import { DocumentScanSessionNotice } from "../components/DocumentScanSessionNotice";
import type { DocumentScanSession } from "../hooks/useDocumentScanSession";
import type { WarehouseDocument } from "../types";

const api = vi.hoisted(() => ({
  receivingRelease: vi.fn(),
  pickingRelease: vi.fn(),
}));

// What the notice's own read answers, set per test: the component owns the
// query, so the test hands it the session the API would.
const read = vi.hoisted(() => ({
  data: undefined as DocumentScanSession | null | undefined,
}));

vi.mock("../hooks/useDocumentScanSession", () => ({
  useDocumentScanSession: vi.fn(() => ({ data: read.data })),
}));

vi.mock("../api/documents_receiving", () => ({
  documentsReceivingApi: { wmsReceivingRelease: api.receivingRelease },
}));

vi.mock("../api/documents_picking", () => ({
  documentsPickingApi: { wmsPickingRelease: api.pickingRelease },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function session(kind: DocumentScanSession["kind"]): DocumentScanSession {
  return {
    kind,
    id: "session-1",
    status: "active",
    started_at: "2026-10-11T08:00:00Z",
    assigned_to: "user-1",
    doneLines: 2,
    totalLines: 3,
  };
}

function renderNotice(
  kind: DocumentScanSession["kind"] = "receiving",
  overrides: Partial<DocumentScanSession> = {},
  document: {
    status?: WarehouseDocument["status"];
    type?: WarehouseDocument["type"];
  } = {},
) {
  read.data = { ...session(kind), ...overrides };
  const onResumeReceiving = vi.fn();
  const onResumePicking = vi.fn();
  const onComplete = vi.fn();
  render(
    <QueryWrapper>
      <DocumentScanSessionNotice
        document={{
          id: "doc-1",
          status: document.status ?? "CONFIRMED",
          type: document.type ?? (kind === "receiving" ? "IN" : "INT"),
          confirmed_at: null,
        }}
        onResumeReceiving={onResumeReceiving}
        onResumePicking={onResumePicking}
        onComplete={onComplete}
        isCompletePending={false}
      />
    </QueryWrapper>,
  );
  return { onResumeReceiving, onResumePicking, onComplete };
}

beforeEach(() => {
  vi.clearAllMocks();
  read.data = session("receiving");
});

describe("DocumentScanSessionNotice", () => {
  it("says nothing when the document has no open session", () => {
    read.data = null;
    render(
      <QueryWrapper>
        <DocumentScanSessionNotice
          document={{
            id: "doc-1",
            status: "CONFIRMED",
            type: "IN",
            confirmed_at: null,
          }}
          onResumeReceiving={vi.fn()}
          onResumePicking={vi.fn()}
          onComplete={vi.fn()}
          isCompletePending={false}
        />
      </QueryWrapper>,
    );

    expect(
      screen.queryByTestId("open-scan-session-notice"),
    ).not.toBeInTheDocument();
  });

  it.each([
    ["receiving", "lines received: 2/3"],
    ["picking", "lines picked: 2/3"],
  ] as const)(
    "says how far the %s session got and that its scans are kept",
    (kind, progress) => {
      renderNotice(kind);

      const notice = screen.getByTestId("open-scan-session-notice");
      expect(notice).toHaveTextContent(progress);
      expect(notice).toHaveTextContent("What was scanned is kept");
    },
  );

  it("resumes a receiving session through the receiving door", async () => {
    const { onResumeReceiving, onResumePicking } = renderNotice("receiving");

    await userEvent.click(
      screen.getByRole("button", { name: "Continue (2/3)" }),
    );

    expect(onResumeReceiving).toHaveBeenCalledTimes(1);
    expect(onResumePicking).not.toHaveBeenCalled();
  });

  it("resumes a picking session through the picking door", async () => {
    const { onResumeReceiving, onResumePicking } = renderNotice("picking");

    await userEvent.click(
      screen.getByRole("button", { name: "Continue (2/3)" }),
    );

    expect(onResumePicking).toHaveBeenCalledTimes(1);
    expect(onResumeReceiving).not.toHaveBeenCalled();
  });

  it("asks before it closes the session, and closes nothing on cancel", async () => {
    renderNotice();

    await userEvent.click(
      screen.getByRole("button", { name: "Discard scans" }),
    );
    expect(
      screen.getByText(/Discarding puts back every scan/),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(api.receivingRelease).not.toHaveBeenCalled();
    expect(api.pickingRelease).not.toHaveBeenCalled();
  });

  it("closes a receiving session through the receiving door", async () => {
    api.receivingRelease.mockResolvedValue(undefined);
    renderNotice("receiving");

    await userEvent.click(
      screen.getByRole("button", { name: "Discard scans" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Discard scans" }),
    );

    await waitFor(() =>
      expect(api.receivingRelease).toHaveBeenCalledWith("doc-1", "session-1"),
    );
    expect(api.pickingRelease).not.toHaveBeenCalled();
  });

  it("closes a picking session through the picking door", async () => {
    api.pickingRelease.mockResolvedValue(undefined);
    renderNotice("picking");

    await userEvent.click(
      screen.getByRole("button", { name: "Discard scans" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Discard scans" }),
    );

    await waitFor(() =>
      expect(api.pickingRelease).toHaveBeenCalledWith("doc-1", "session-1"),
    );
    expect(api.receivingRelease).not.toHaveBeenCalled();
  });

  describe("a paused session", () => {
    it.each([
      ["receiving", "IN"],
      ["picking", "INT"],
    ] as const)(
      "completes the %s document with what was scanned in one step",
      async (kind, type) => {
        const { onComplete } = renderNotice(
          kind,
          { status: "paused" },
          { type },
        );

        await userEvent.click(
          screen.getByRole("button", { name: "Complete and post stock" }),
        );

        expect(onComplete).toHaveBeenCalledTimes(1);
      },
    );

    it("leaves a dispatch to its Packing step", () => {
      renderNotice("picking", { status: "paused" }, { type: "OUT" });

      expect(
        screen.queryByRole("button", { name: "Complete and post stock" }),
      ).not.toBeInTheDocument();
    });

    it("offers no completion while somebody is still scanning", () => {
      renderNotice("receiving", { status: "active" });

      expect(
        screen.queryByRole("button", { name: "Complete and post stock" }),
      ).not.toBeInTheDocument();
    });
  });

  describe("a finished scan over a document nobody completed", () => {
    it.each([
      ["receiving", "IN", /receiving scan is finished/],
      ["picking", "INT", /picking scan is finished/],
    ] as const)(
      "names the unbooked %s and completes it in one step",
      async (kind, type, sentence) => {
        const { onComplete } = renderNotice(
          kind,
          { status: "finished" },
          { type },
        );

        expect(screen.getByText(sentence)).toBeInTheDocument();
        expect(screen.getByText(/no stock is booked yet/)).toBeInTheDocument();
        expect(
          screen.queryByRole("button", { name: "Discard scans" }),
        ).not.toBeInTheDocument();
        await userEvent.click(
          screen.getByRole("button", { name: "Complete and post stock" }),
        );

        expect(onComplete).toHaveBeenCalledTimes(1);
      },
    );

    it("points a dispatch at its Packing step instead of a second completion", () => {
      renderNotice("picking", { status: "finished" }, { type: "OUT" });

      expect(screen.getByText(/in the Packing step below/)).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Complete and post stock" }),
      ).not.toBeInTheDocument();
    });

    it("says nothing while the document waits for approval", () => {
      renderNotice(
        "receiving",
        { status: "finished" },
        { status: "PENDING_APPROVAL" },
      );

      expect(
        screen.queryByTestId("unbooked-scan-session-notice"),
      ).not.toBeInTheDocument();
    });
  });
});
