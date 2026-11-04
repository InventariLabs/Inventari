import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import { PostedActionResult } from "./PostedActionResult";

function posted(overrides: Partial<WarehouseDocument> = {}): WarehouseDocument {
  return {
    id: "doc-1",
    number: "OUT/2026/007",
    type: "OUT",
    status: "COMPLETED",
    lines: [{ id: "l1" }, { id: "l2" }],
    ...overrides,
  } as unknown as WarehouseDocument;
}

function renderResult(
  document: WarehouseDocument,
  lineCount?: number,
  details?: React.ReactNode,
  action: "receive" | "issue" | "move" = "issue",
  waitingIn: string | null = null,
) {
  const onAnother = vi.fn();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <PostedActionResult
          document={document}
          action={action}
          waitingIn={waitingIn}
          lineCount={lineCount}
          details={details}
          onAnother={onAnother}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { onAnother };
}

describe("PostedActionResult", () => {
  it("says the goods wait in the receiving area after a two-step receipt", () => {
    renderResult(
      posted({ type: "IN", number: "PZ/2026/001" }),
      1,
      undefined,
      "receive",
      "Receiving",
    );
    expect(
      screen.getByText(/The goods wait in Receiving, and a putaway task/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/The goods are in stock/),
    ).not.toBeInTheDocument();
  });

  it("keeps 'in stock' for a receipt that landed on a shelf", () => {
    renderResult(posted({ type: "IN" }), 1, undefined, "receive");
    expect(screen.getByText(/The goods are in stock/)).toBeInTheDocument();
  });

  it("says what moved, links the document and says what undo will do", () => {
    renderResult(posted(), 3);

    expect(
      screen.getByRole("heading", { name: "Issued 3 lines" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "OUT/2026/007" })).toHaveAttribute(
      "href",
      "/warehouse/documents/doc-1",
    );
    const undo = screen.getByRole("button", { name: "Undo issue" });
    expect(undo).toHaveAccessibleDescription(
      /puts the goods back in stock and writes a correction to OUT\/2026\/007/,
    );
  });

  it("undoes the posting and names the reversal instead of offering undo again", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/v1/warehouse/documents/doc-1/undo", () =>
        HttpResponse.json({
          id: "rev-1",
          number: "COR/2026/002",
          type: "CORRECTION",
          status: "COMPLETED",
        }),
      ),
    );
    renderResult(posted());

    await user.click(screen.getByRole("button", { name: "Undo issue" }));

    expect(
      await screen.findByText(/reversal COR\/2026\/002 is in the history/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Undo issue" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View reversal" })).toHaveAttribute(
      "href",
      "/warehouse/documents/rev-1",
    );
    // The panel tells the undo now; it no longer says the goods left stock
    // above the notice that they are back.
    expect(
      screen.getByRole("heading", { name: "Issue undone" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/The stock is as it was before\./)).toBeVisible();
    expect(screen.queryByText(/have left stock/)).not.toBeInTheDocument();
  });

  it("keeps telling the posting while the undo waits for an approval", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/v1/warehouse/documents/doc-1/undo", () =>
        HttpResponse.json({
          id: "rev-1",
          number: "COR/2026/002",
          type: "CORRECTION",
          status: "PENDING_APPROVAL",
        }),
      ),
    );
    renderResult(posted());

    await user.click(screen.getByRole("button", { name: "Undo issue" }));

    expect(
      await screen.findByText(
        /reversal COR\/2026\/002 posts when it is approved/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Issued 2 lines" }),
    ).toBeInTheDocument();
  });

  it("drops the caller's details once a reversal exists", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/v1/warehouse/documents/doc-1/undo", () =>
        HttpResponse.json({
          id: "rev-1",
          number: "COR/2026/002",
          type: "CORRECTION",
          status: "COMPLETED",
        }),
      ),
    );
    renderResult(posted(), 2, "The order is now received in full.");

    expect(
      screen.getByText("The order is now received in full."),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Undo issue" }));

    expect(
      await screen.findByText(/reversal COR\/2026\/002 is in the history/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("The order is now received in full."),
    ).not.toBeInTheDocument();
  });

  it("keeps the server's refusal on the screen when the stock was used since", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/v1/warehouse/documents/doc-1/undo", () =>
        HttpResponse.json(
          {
            detail: {
              code: "document_undo_stock_used",
              message: "The stock was used since; correct it instead",
            },
          },
          { status: 422 },
        ),
      ),
    );
    renderResult(posted());

    await user.click(screen.getByRole("button", { name: "Undo issue" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The stock was used since; correct it instead",
    );
  });

  it("offers a write-off its own undo", () => {
    renderResult(posted({ type: "SCRAP", number: "SCR/2026/001" }));

    expect(
      screen.getByRole("button", { name: "Undo write-off" }),
    ).toBeInTheDocument();
  });

  it("ends a write-off on a write-off result, not on an issue", () => {
    renderResult(posted({ type: "SCRAP", number: "SCR/2026/001" }));

    expect(
      screen.getByRole("heading", { name: "Wrote off 2 lines" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Write off more" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Issued/)).not.toBeInTheDocument();
  });

  it("says a document stopped for approval moves stock later, with nothing to undo", () => {
    renderResult(posted({ status: "PENDING_APPROVAL" }));

    expect(
      screen.getByRole("heading", { name: "Sent for approval" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/The stock moves when it is approved/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Undo/ }),
    ).not.toBeInTheDocument();
  });

  it("starts the same action again", async () => {
    const user = userEvent.setup();
    const { onAnother } = renderResult(posted());

    await user.click(screen.getByRole("button", { name: "Issue more" }));

    expect(onAnother).toHaveBeenCalledOnce();
  });
});
