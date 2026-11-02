import { create } from "zustand";
import { useScanStore } from "./scanStore";

/**
 * What one product form hands to the next — and nothing else.
 *
 * Putting several things away in a row is the reason this exists: they land
 * on the same shelf and usually under the same category, and retyping both
 * every time is the difference between the batch being done and abandoned.
 *
 * Everything else that used to be remembered — the name, the brand, the unit,
 * the weight, the quantity, the expiry date, the custom fields — described one
 * product, not the batch. Carried onto the next record it produced data nobody
 * typed: a tin of peas filed as cold cuts and given the expiry date of the
 * carton before it. A default that is wrong more often than right is not a
 * shortcut, so those are gone rather than made optional.
 */
interface FormMemory {
  lastItem: {
    category_id?: string;
    location_id?: string;
  } | null;
  setLastItem: (data: RememberedItemInput) => void;
  clear: () => void;
}

/** The submitted payload, as far as this store is concerned. */
interface RememberedItemInput {
  category_id?: string | null;
  location_id?: string | null;
}

export const useFormMemoryStore = create<FormMemory>((set) => ({
  lastItem: null,
  setLastItem: (data) =>
    set({
      lastItem: {
        category_id: data.category_id ?? undefined,
        location_id: data.location_id ?? undefined,
      },
    }),
  clear: () => set({ lastItem: null }),
}));

// The same memory for the length of a tab, so it changes hands with the
// scanner's. Listening from here keeps it out of the startup path: a store
// nobody has loaded yet has nothing to forget.
useScanStore.subscribe((scan, before) => {
  if (scan.owner !== before.owner) useFormMemoryStore.getState().clear();
});
