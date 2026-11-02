import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import type { StorageLocationSummary } from "@/types";
import type { ItemFormData } from "./useItemForm";

interface UseMissingPicksProps {
  /** Whether the place the form holds is one the picker offers; `undefined`
   *  until that is known. */
  storageOffered: boolean | undefined;
  /** The categories the picker actually offers, once they have arrived. */
  categories: Array<{ id: string }> | undefined;
  /** What the form is holding, for the two ids being checked. */
  formData: ItemFormData;
  setFormData: React.Dispatch<React.SetStateAction<ItemFormData>>;
  /** What the form holds only because it was remembered, not chosen here. */
  remembered: { storageId: string; categoryId: string };
}

/**
 * A remembered pick the form cannot offer does not seed the field.
 *
 * The batch memory and the scan memory survive a page reload, a profile
 * switch and a deleted location, and they come back from `localStorage`
 * whether or not the record behind them still exists. Seeded anyway they
 * produced the worst possible state: the field showing its placeholder while
 * the form held an id, the shortcut beside it linking to "not found", and a
 * product saveable into a place the form could not name — the inventory
 * corpus turned jars into laptops this way. Both fields share the rule.
 *
 * Only the reader's own pick is announced, once per opening. A remembered one
 * leaves without a word: the reader did not choose it in this form and cannot
 * see it, so "this place is gone" would point at nothing — and after a demo
 * reset it was the first thing the scanner ever said to a returning visitor.
 */
export function useMissingPicks({
  storageOffered,
  categories,
  formData,
  setFormData,
  remembered,
}: UseMissingPicksProps) {
  const { t } = useTranslation("items");
  const announcedStorage = useRef(false);
  useEffect(() => {
    const chosen = formData.location_id as string;
    if (!chosen || storageOffered !== false) return;
    setFormData((prev) => ({ ...prev, location_id: "" }));
    if (chosen === remembered.storageId || announcedStorage.current) return;
    announcedStorage.current = true;
    toast.info(t("items:validation.storageUnavailable"));
  }, [
    storageOffered,
    formData.location_id,
    setFormData,
    remembered.storageId,
    t,
  ]);

  const announcedCategory = useRef(false);
  useEffect(() => {
    if (!categories) return;
    const chosen = formData.category_id;
    if (!chosen || categories.some((c) => c.id === chosen)) return;
    setFormData((prev) => ({ ...prev, category_id: "" }));
    if (chosen === remembered.categoryId || announcedCategory.current) return;
    announcedCategory.current = true;
    toast.info(t("items:validation.categoryUnavailable"));
  }, [categories, formData.category_id, setFormData, remembered.categoryId, t]);
}

export type { StorageLocationSummary };
