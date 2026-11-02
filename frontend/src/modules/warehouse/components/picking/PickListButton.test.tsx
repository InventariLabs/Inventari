import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { render, screen, waitFor } from "@/test/utils";
import { PickListButton } from "./PickListButton";

const { dispatchPickListPdf, sessionPickListPdf, downloadBlob } = vi.hoisted(
  () => ({
    dispatchPickListPdf: vi.fn(),
    sessionPickListPdf: vi.fn(),
    downloadBlob: vi.fn(),
  }),
);

vi.mock("@/modules/warehouse/api/documents_picking", () => ({
  documentsPickingApi: { dispatchPickListPdf, sessionPickListPdf },
}));
vi.mock("@/utils/helpers", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/utils/helpers")>()),
  downloadBlob,
}));

describe("PickListButton", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    dispatchPickListPdf.mockResolvedValue(new Blob(["pdf"]));
    sessionPickListPdf.mockResolvedValue(new Blob(["pdf"]));
  });

  it("prints a dispatch's list under its number", async () => {
    const user = userEvent.setup();
    render(<PickListButton documentId="doc-1" number="OUT/2026/001" />);

    await user.click(screen.getByRole("button", { name: "Print pick list" }));

    await waitFor(() => expect(downloadBlob).toHaveBeenCalledOnce());
    expect(dispatchPickListPdf).toHaveBeenCalledWith("doc-1", "en");
    expect(sessionPickListPdf).not.toHaveBeenCalled();
    expect(downloadBlob).toHaveBeenCalledWith(
      expect.any(Blob),
      "pick_list_OUT-2026-001.pdf",
    );
  });

  it("prints a session's list, in the screen's order, when it is given the session", async () => {
    const user = userEvent.setup();
    render(
      <PickListButton
        documentId="doc-1"
        sessionId="session-1"
        number="OUT/2026/001"
        iconOnly
      />,
    );

    await user.click(screen.getByRole("button", { name: "Print pick list" }));

    await waitFor(() => expect(downloadBlob).toHaveBeenCalledOnce());
    expect(sessionPickListPdf).toHaveBeenCalledWith("doc-1", "session-1", "en");
    expect(dispatchPickListPdf).not.toHaveBeenCalled();
  });

  it("downloads nothing when the list cannot be made", async () => {
    dispatchPickListPdf.mockRejectedValue(new Error("boom"));
    const user = userEvent.setup();
    render(<PickListButton documentId="doc-1" number="OUT/1" />);

    await user.click(screen.getByRole("button", { name: "Print pick list" }));

    await waitFor(() => expect(dispatchPickListPdf).toHaveBeenCalled());
    expect(downloadBlob).not.toHaveBeenCalled();
  });
});
