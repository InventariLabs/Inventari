/**
 * The protocol preview used to open as a blob URL in a new tab, and a blob
 * inherits the origin of the page that made it — so a Jinja layout an
 * organization admin can edit ran as the application, with the reader's
 * session. The sandbox attribute is the whole fix, which makes it worth a
 * test that fails if someone loosens it.
 *
 * The footer is the other half of the same rationale: the sandbox is why
 * there is no Print button, and the download is therefore the route to
 * paper — so it has to be reachable from the dialog whose description
 * points at it.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ProtocolPreviewDialog } from "./ProtocolPreviewDialog";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
  }),
}));

describe("ProtocolPreviewDialog", () => {
  it("renders the protocol with nothing granted back", () => {
    render(
      <ProtocolPreviewDialog
        html="<p>Handover</p>"
        onClose={vi.fn()}
        onDownloadPdf={vi.fn()}
      />,
    );

    const frame = screen.getByTitle("Print preview") as HTMLIFrameElement;
    expect(frame.getAttribute("sandbox")).toBe("");
    expect(frame.getAttribute("srcdoc")).toContain("Handover");
    expect(frame.getAttribute("src")).toBeNull();
  });

  it("stays closed until there is something to show", () => {
    render(
      <ProtocolPreviewDialog
        html={null}
        onClose={vi.fn()}
        onDownloadPdf={vi.fn()}
      />,
    );

    expect(screen.queryByTitle("Print preview")).toBeNull();
  });

  it("offers the download the description promises", async () => {
    const onDownloadPdf = vi.fn();
    render(
      <ProtocolPreviewDialog
        html="<p>Handover</p>"
        onClose={vi.fn()}
        onDownloadPdf={onDownloadPdf}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Download PDF" }));

    expect(onDownloadPdf).toHaveBeenCalledTimes(1);
  });
});
