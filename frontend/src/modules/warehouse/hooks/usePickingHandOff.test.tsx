import { StrictMode } from "react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { warehouseDocument } from "@/test/factories/documents";
import type { ShipmentCreate } from "@/modules/warehouse/api/shipments";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import {
  useHandedOverCompletion,
  usePickingHandOff,
} from "./usePickingHandOff";

function List({ onLeave }: { onLeave: () => void }) {
  const handOff = usePickingHandOff(onLeave);
  return (
    <>
      <button onClick={() => handOff.onClose(true, { carrier: "DHL" }, "d1")}>
        Complete and book
      </button>
      <button onClick={() => handOff.onClose(false)}>Close</button>
      <button
        onClick={() =>
          handOff.onPack({ carrier: "DPD", trackingNumber: "" }, "d1")
        }
      >
        Pack
      </button>
    </>
  );
}

function DocumentPage({
  doc,
  complete,
}: {
  doc: WarehouseDocument;
  complete: (shipment?: ShipmentCreate) => void;
}) {
  useHandedOverCompletion(doc, complete);
  const location = useLocation();
  return (
    <p>
      {`on ${location.pathname}${location.hash}`}
      {location.state ? ` with ${JSON.stringify(location.state)}` : ""}
    </p>
  );
}

function renderApp(status: WarehouseDocument["status"] = "CONFIRMED") {
  const onLeave = vi.fn();
  const complete = vi.fn();
  render(
    <StrictMode>
      <MemoryRouter initialEntries={["/warehouse/documents"]}>
        <Routes>
          <Route
            path="/warehouse/documents"
            element={<List onLeave={onLeave} />}
          />
          <Route
            path="/warehouse/documents/:id"
            element={
              <DocumentPage
                doc={warehouseDocument({ id: "d1", status })}
                complete={complete}
              />
            }
          />
        </Routes>
      </MemoryRouter>
    </StrictMode>,
  );
  return { onLeave, complete };
}

describe("a one-document picking session started from a list", () => {
  it("is completed on the document's page, once, with the carrier", async () => {
    const { onLeave, complete } = renderApp();

    await userEvent.click(
      screen.getByRole("button", { name: "Complete and book" }),
    );

    expect(onLeave).toHaveBeenCalledOnce();
    expect(
      await screen.findByText("on /warehouse/documents/d1"),
    ).toBeInTheDocument();
    // Spent: the history entry no longer carries it, so a reload or Back
    // to this page does not complete the document a second time.
    expect(complete).toHaveBeenCalledOnce();
    expect(complete).toHaveBeenCalledWith({ carrier: "DHL" });
  });

  it("leaves a document no longer confirmed as it is", async () => {
    const { complete } = renderApp("COMPLETED");

    await userEvent.click(
      screen.getByRole("button", { name: "Complete and book" }),
    );

    expect(
      await screen.findByText("on /warehouse/documents/d1"),
    ).toBeInTheDocument();
    expect(complete).not.toHaveBeenCalled();
  });

  it("lands on the Pack step with the carrier it took", async () => {
    const { complete } = renderApp();

    await userEvent.click(screen.getByRole("button", { name: "Pack" }));

    expect(
      await screen.findByText(
        'on /warehouse/documents/d1#pack with {"shipment":{"carrier":"DPD","trackingNumber":""}}',
      ),
    ).toBeInTheDocument();
    expect(complete).not.toHaveBeenCalled();
  });

  it("stays on the list when the session covered several documents", async () => {
    const { onLeave, complete } = renderApp();

    await userEvent.click(screen.getByRole("button", { name: "Close" }));

    expect(onLeave).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Pack" })).toBeInTheDocument();
    expect(complete).not.toHaveBeenCalled();
  });
});
