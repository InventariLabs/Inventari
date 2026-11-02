import { create } from "zustand";

/**
 * Which products' labels the print sheet is open for, if any.
 *
 * The list's bulk action hands its handler identifiers and nothing else, and
 * has no tree to render a sheet into; it puts the selection here and the
 * sheet's host, mounted once in the shell, opens on it.
 */
interface ProductLabelRequestState {
  itemIds: string[] | null;
  open: (itemIds: string[]) => void;
  close: () => void;
}

export const useProductLabelRequest = create<ProductLabelRequestState>(
  (set) => ({
    itemIds: null,
    open: (itemIds) => set({ itemIds }),
    close: () => set({ itemIds: null }),
  }),
);
