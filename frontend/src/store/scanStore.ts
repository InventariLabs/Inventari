import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * The memory is persistent on the device, on purpose: a batch-scan session
 * spans page reloads, and the values it carries are exactly the ones typed
 * again and again on such a day. It is not a trap — there are two ways out,
 * both one click from where the values are seen: the carried-over notice in
 * the quick-add form clears them (for the form and for the products after
 * it), and saving a product *without* a category clears the remembered
 * category. A remembered value survives only until something says otherwise.
 *
 * It is one identity's memory, and it knows whose: `claimFor` forgets it the
 * moment anyone else is signed in on this device, whichever road they came by.
 */

export interface StorageContext {
  id: string;
  name: string;
  icon: string;
  type_code?: string;
}

interface ScanState {
  /** Who the memory below belongs to; `null` for a memory of unknown origin. */
  owner: string | null;
  storageContext: StorageContext | null;
  lastStorageId: string | null;
  lastCategoryId: string | null;
  setStorageContext: (context: StorageContext | null) => void;
  clearStorageContext: () => void;
  setLastUsed: (storageId: string, categoryId?: string) => void;
  /** Forgets the remembered shelf and category — the move the quick-add
   *  form's carried-over notice offers. */
  clearLastUsed: () => void;
  /** Forgets everything remembered about where things were put — the
   *  teardown that runs when the identity leaves. */
  clear: () => void;
  /** Hands the memory to whoever is signed in: theirs stays, anybody else's
   *  is forgotten. */
  claimFor: (owner: string) => void;
}

export const useScanStore = create<ScanState>()(
  persist(
    (set, get) => ({
      owner: null,
      storageContext: null,
      lastStorageId: null,
      lastCategoryId: null,
      setStorageContext: (storageContext) => set({ storageContext }),
      clearStorageContext: () => set({ storageContext: null }),
      // A save without a category says "this product had none" — carrying
      // the previous category forward would file it under whatever was
      // remembered, which is how tins of peas ended up under cold cuts.
      setLastUsed: (storageId, categoryId) =>
        set({ lastStorageId: storageId, lastCategoryId: categoryId ?? null }),
      clearLastUsed: () => set({ lastStorageId: null, lastCategoryId: null }),
      clear: () =>
        set({
          storageContext: null,
          lastStorageId: null,
          lastCategoryId: null,
        }),
      claimFor: (owner) => {
        if (get().owner === owner) return;
        set({
          owner,
          storageContext: null,
          lastStorageId: null,
          lastCategoryId: null,
        });
      },
    }),
    {
      name: "inventari-scan",
    },
  ),
);
