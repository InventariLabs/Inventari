import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { render, screen } from "@/test/utils";
import WmsPickingSummary from "./WmsPickingSummary";
import type {
  WmsPickLine,
  WmsPickSession,
} from "@/modules/warehouse/api/documents";

const picked: WmsPickLine = {
  id: "line-1",
  document_line_id: "doc-line-1",
  pick_order: 1,
  status: "picked",
  picked_quantity: 5,
  product_name: "Widget",
  lot_name: null,
  bin_location: "A-01",
  expected_quantity: 5,
  uom_symbol: "pcs",
};

const session: WmsPickSession = {
  id: "session-1",
  document_id: "doc-1",
  status: "completed",
  lines: [picked],
  documents: [],
  total_lines: 1,
  picked_lines: 1,
  pending_lines: 0,
  shelf_scan_required: false,
};

describe("WmsPickingSummary", () => {
  it("says before the tap that closing books the stock, only when it does", () => {
    const props = { session, lines: [picked], onClose: vi.fn() };
    const { rerender } = render(<WmsPickingSummary {...props} />);
    expect(screen.queryByText(/books the stock/i)).not.toBeInTheDocument();

    rerender(<WmsPickingSummary {...props} completesDocument />);
    expect(screen.getByText(/books the stock/i)).toBeInTheDocument();
  });
  it("books only from the button that says so: Escape leaves the document as picked", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const onLeave = vi.fn();
    render(
      <WmsPickingSummary
        session={session}
        lines={[picked]}
        completesDocument
        onClose={onClose}
        onLeave={onLeave}
        onPack={vi.fn()}
      />,
    );

    await user.keyboard("{Escape}");

    expect(onClose).not.toHaveBeenCalled();
    expect(onLeave).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: "Close" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Complete and book" }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("lets a dispatch go to packing instead of completing it", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const onPack = vi.fn();
    render(
      <WmsPickingSummary
        session={session}
        lines={[picked]}
        onClose={onClose}
        onPack={onPack}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Pack" }));

    expect(onPack).toHaveBeenCalledOnce();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("opens without raising the keyboard on the optional carrier", () => {
    render(
      <WmsPickingSummary
        session={session}
        lines={[picked]}
        onClose={vi.fn()}
        onPack={vi.fn()}
      />,
    );

    const carrier = screen.getByLabelText("Carrier");
    expect(carrier).not.toHaveFocus();
    expect(document.activeElement?.tagName).not.toBe("INPUT");
    expect(screen.getByText("Picking Complete")).toHaveFocus();
  });

  it("offers no packing where nothing is packed", () => {
    render(
      <WmsPickingSummary
        session={session}
        lines={[picked]}
        onClose={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: "Pack" })).toBeNull();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
  });

  describe("over several documents", () => {
    const shortLine: WmsPickLine = {
      ...picked,
      id: "line-2",
      document_id: "doc-2",
      status: "short",
      picked_quantity: 2,
    };
    const first: WmsPickLine = { ...picked, document_id: "doc-1" };
    const several: WmsPickSession = {
      ...session,
      documents: [
        { document_id: "doc-1", document_number: "OUT/2026/001" },
        { document_id: "doc-2", document_number: "OUT/2026/002" },
      ],
    } as WmsPickSession;

    it("calls each document picked, not completed, and links to it", () => {
      render(
        <WmsPickingSummary
          session={several}
          lines={[first, shortLine]}
          onClose={vi.fn()}
        />,
      );

      expect(screen.getByText("Picked")).toBeInTheDocument();
      expect(screen.getByText("Picked with shortages")).toBeInTheDocument();
      expect(screen.queryByText(/completed/i)).toBeNull();
      expect(
        screen.getByRole("link", { name: "OUT/2026/002" }),
      ).toHaveAttribute("href", "/warehouse/documents/doc-2");
    });

    it("does not call a document with a skipped line picked", () => {
      render(
        <WmsPickingSummary
          session={several}
          lines={[
            first,
            { ...shortLine, status: "skipped", picked_quantity: 0 },
          ]}
          onClose={vi.fn()}
        />,
      );

      expect(screen.getByText("Picked")).toBeInTheDocument();
      expect(screen.getByText("Picked with shortages")).toBeInTheDocument();
    });

    it("offers no carrier and no Pack for only the page's document", async () => {
      const user = userEvent.setup();
      const onClose = vi.fn();
      render(
        <WmsPickingSummary
          session={several}
          lines={[first, shortLine]}
          onClose={onClose}
          onPack={vi.fn()}
        />,
      );

      expect(screen.queryByRole("group", { name: "Shipping" })).toBeNull();
      expect(screen.queryByLabelText("Carrier")).toBeNull();
      expect(screen.queryByRole("button", { name: "Pack" })).toBeNull();
      await user.click(screen.getByRole("button", { name: "Close" }));
      expect(onClose).toHaveBeenCalledWith(undefined);
    });

    it("says each document is packed and completed from its own page", () => {
      render(
        <WmsPickingSummary
          session={several}
          lines={[first, shortLine]}
          onClose={vi.fn()}
        />,
      );

      expect(
        screen.getByText(/open each one to pack and complete it/i),
      ).toBeInTheDocument();
    });
  });

  it("adds no such note over a single document", () => {
    render(
      <WmsPickingSummary
        session={session}
        lines={[picked]}
        onClose={vi.fn()}
      />,
    );

    expect(screen.queryByText(/open each one/i)).toBeNull();
  });

  describe("with a skipped line", () => {
    const skippedLine: WmsPickLine = {
      ...picked,
      id: "line-3",
      document_line_id: "doc-line-3",
      status: "skipped",
      picked_quantity: 0,
      product_name: "Butter",
      expected_quantity: 4,
    };
    const props = {
      session,
      lines: [picked, skippedLine],
      completesDocument: true,
    };

    it("says what a skipped line becomes, in the guide's words", () => {
      render(
        <WmsPickingSummary
          {...props}
          onClose={vi.fn()}
          onUndoSkip={vi.fn()}
          onAnswerSkip={vi.fn()}
        />,
      );

      expect(
        screen.getByText(
          "A skipped line is not picked. Undo the skip to pick it, or say " +
            "what it becomes when the document is completed: Backorder " +
            "records it short under Shortage and creates a backorder draft " +
            "for it; Not sent records it under Other and closes the gap.",
        ),
      ).toBeInTheDocument();
    });

    it("takes the skip back from the summary", async () => {
      const user = userEvent.setup();
      const onUndoSkip = vi.fn();
      render(
        <WmsPickingSummary
          {...props}
          onClose={vi.fn()}
          onUndoSkip={onUndoSkip}
          onAnswerSkip={vi.fn()}
        />,
      );

      await user.click(screen.getByRole("button", { name: "Undo skip" }));

      expect(onUndoSkip).toHaveBeenCalledWith(skippedLine);
    });

    it("records the outcome the person chose", async () => {
      const user = userEvent.setup();
      const onAnswerSkip = vi.fn();
      render(
        <WmsPickingSummary
          {...props}
          onClose={vi.fn()}
          onUndoSkip={vi.fn()}
          onAnswerSkip={onAnswerSkip}
        />,
      );

      await user.click(screen.getByRole("button", { name: "Backorder" }));
      await user.click(screen.getByRole("button", { name: "Not sent" }));

      expect(onAnswerSkip).toHaveBeenNthCalledWith(1, skippedLine, "SHORTAGE");
      expect(onAnswerSkip).toHaveBeenNthCalledWith(2, skippedLine, "OTHER");
    });

    it("completes nothing while a skipped line is unanswered", async () => {
      const user = userEvent.setup();
      const onClose = vi.fn();
      const onPack = vi.fn();
      render(
        <WmsPickingSummary
          {...props}
          onClose={onClose}
          onPack={onPack}
          onUndoSkip={vi.fn()}
          onAnswerSkip={vi.fn()}
        />,
      );

      await user.click(
        screen.getByRole("button", { name: "Complete and book" }),
      );
      await user.click(screen.getByRole("button", { name: "Pack" }));
      await user.keyboard("{Escape}");

      expect(onClose).not.toHaveBeenCalled();
      expect(onPack).not.toHaveBeenCalled();
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Answer every skipped line first",
      );
    });

    it("names the chosen outcome once the line is answered", async () => {
      const user = userEvent.setup();
      const handlers = {
        onClose: vi.fn(),
        onUndoSkip: vi.fn(),
        onAnswerSkip: vi.fn(),
      };
      const { rerender } = render(
        <WmsPickingSummary {...props} {...handlers} />,
      );

      await user.click(screen.getByRole("button", { name: "Backorder" }));
      // What the server answers: the line short by all of it.
      rerender(
        <WmsPickingSummary
          {...props}
          {...handlers}
          lines={[picked, { ...skippedLine, status: "short" }]}
        />,
      );

      expect(
        screen.getByText(/^Butter — 0\/4 .* · Backorder$/),
      ).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Undo skip" })).toBeNull();
    });
  });
});
