import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryWrapper } from "@/test/queryWrapper";
import { documentLine, warehouseDocument } from "@/test/factories/documents";
import { useDocumentLineNames } from "./useDocumentLineNames";

const get = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ api: { get } }));

const docWith = (lines: ReturnType<typeof documentLine>[]) =>
  warehouseDocument({ id: "doc-1", lines });

describe("useDocumentLineNames", () => {
  beforeEach(() => {
    get.mockReset();
  });

  it("names a line that carries only an item id", async () => {
    get.mockResolvedValue({ data: { name: "Gouda 250 g" } });
    const doc = docWith([documentLine({ id: "l-1", item_id: "item-1" })]);

    const { result } = renderHook(() => useDocumentLineNames(doc), {
      wrapper: QueryWrapper,
    });

    await waitFor(() =>
      expect(result.current?.lines[0].name).toBe("Gouda 250 g"),
    );
    expect(get).toHaveBeenCalledWith("/items/item-1");
  });

  it("reads each item once however many lines name it", async () => {
    get.mockResolvedValue({ data: { name: "Gouda 250 g" } });
    const doc = docWith([
      documentLine({ id: "l-1", item_id: "item-1" }),
      documentLine({ id: "l-2", item_id: "item-1" }),
    ]);

    const { result } = renderHook(() => useDocumentLineNames(doc), {
      wrapper: QueryWrapper,
    });

    await waitFor(() =>
      expect(result.current?.lines[1].name).toBe("Gouda 250 g"),
    );
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("asks for nothing when every line already has a name", () => {
    const doc = docWith([
      documentLine({ id: "l-1", item_id: "item-1", name: "Widget" }),
      documentLine({ id: "l-2", item_id: null, name: null }),
    ]);

    const { result } = renderHook(() => useDocumentLineNames(doc), {
      wrapper: QueryWrapper,
    });

    expect(get).not.toHaveBeenCalled();
    expect(result.current).toBe(doc);
  });

  it("keeps the document as it was when the item cannot be read", async () => {
    get.mockRejectedValue(new Error("403"));
    const doc = docWith([documentLine({ id: "l-1", item_id: "item-1" })]);

    const { result } = renderHook(() => useDocumentLineNames(doc), {
      wrapper: QueryWrapper,
    });

    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(result.current).toBe(doc);
  });

  it("passes an unloaded document through", () => {
    const { result } = renderHook(() => useDocumentLineNames(undefined), {
      wrapper: QueryWrapper,
    });
    expect(result.current).toBeUndefined();
  });
});
