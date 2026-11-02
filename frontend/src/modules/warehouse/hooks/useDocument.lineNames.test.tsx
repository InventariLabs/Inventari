import { describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryWrapper } from "@/test/queryWrapper";
import { documentLine, warehouseDocument } from "@/test/factories/documents";
import { useDocument } from "./useDocuments";

const mocks = vi.hoisted(() => ({ getById: vi.fn(), get: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ api: { get: mocks.get } }));
vi.mock("@/modules/warehouse/api/documents", () => ({
  documentsApi: { getById: mocks.getById },
}));

describe("useDocument", () => {
  it("hands the screen a name for a line the server left unnamed", async () => {
    // Both the lines table and the execution panel read the document from
    // here, so one place names the line for both.
    mocks.getById.mockResolvedValue(
      warehouseDocument({
        id: "doc-1",
        lines: [documentLine({ id: "l-1", item_id: "item-1", name: null })],
      }),
    );
    mocks.get.mockResolvedValue({ data: { name: "Gouda 250 g" } });

    const { result } = renderHook(() => useDocument("doc-1"), {
      wrapper: QueryWrapper,
    });

    await waitFor(() =>
      expect(result.current.data?.lines[0].name).toBe("Gouda 250 g"),
    );
  });
});
