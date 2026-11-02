import { renderHook, act } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { documentLine, warehouseDocument } from "@/test/factories/documents";
import * as scanSessionHooks from "@/modules/warehouse/hooks/useDocumentScanSession";
import { useExecuteDoor } from "./useExecuteDoor";

vi.mock("@/modules/warehouse/hooks/useDocumentScanSession", () => ({
  useDocumentScanSession: vi.fn(),
}));

const navigate = vi.hoisted(() => vi.fn());
vi.mock("react-router-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router-dom")>()),
  useNavigate: () => navigate,
}));

/** A confirmed dispatch one of whose two lines came off the shelf. */
const halfPicked = warehouseDocument({
  type: "OUT",
  status: "CONFIRMED",
  lines: [
    documentLine({ id: "a", quantity: "2", done_quantity: "2" }),
    documentLine({ id: "b", quantity: "1", done_quantity: "0" }),
  ],
});

function givenSession(status: "active" | "paused" | "finished" | null) {
  vi.mocked(scanSessionHooks.useDocumentScanSession).mockReturnValue({
    data: status && { kind: "picking", id: "s1", status },
    isPending: false,
  } as unknown as ReturnType<typeof scanSessionHooks.useDocumentScanSession>);
}

function pressExecute() {
  const setOpen = vi.fn();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <MemoryRouter>{children}</MemoryRouter>
  );
  const { result } = renderHook(
    () => useExecuteDoor(halfPicked, false, setOpen),
    { wrapper },
  );
  act(() => result.current.execute());
  return setOpen;
}

describe("useExecuteDoor", () => {
  beforeEach(() => navigate.mockClear());

  it("leads a picked dispatch to its Pack step once picking is over", () => {
    givenSession("finished");
    const setOpen = pressExecute();
    expect(navigate).toHaveBeenCalledWith({ hash: "#pack" }, { replace: true });
    expect(setOpen).not.toHaveBeenCalled();
  });

  it.each(["active", "paused"] as const)(
    "opens the execution panel while a picking session is %s, as the Pack step is not on the page",
    (status) => {
      givenSession(status);
      const setOpen = pressExecute();
      expect(setOpen).toHaveBeenCalledWith(true);
      expect(navigate).not.toHaveBeenCalled();
    },
  );
});
