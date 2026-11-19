import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { extractApiError, ReadableError } from "@/lib/errors";
import type { RegisterBeforeSubmit } from "@/lib/moduleRegistry";
import type { ProductTemplateNutritionInfo } from "@/lib/api/productTemplates";
import type { Item } from "@/types";
import { productNutrition } from "../productNutrition";
import { useUpdateNutrition } from "./useNutrition";

/** What the product sheet's slot hands over (`item_edit_extra`). */
interface SheetSlotData {
  item?: Item;
  /** Run before the sheet's own save, and report unsaved input. */
  registerBeforeSubmit?: RegisterBeforeSubmit;
  reportDirty?: (dirty: boolean) => void;
}

/**
 * The hand-entry block of the product sheet: the figures being typed, their
 * save to the product, and the two things the sheet needs to know about them.
 *
 * Typed figures are the sheet's unsaved edit like any other field: its Save
 * changes saves them first (a refusal stops the whole save), and closing the
 * sheet over them asks.
 */
export function useManualNutrition(data?: SheetSlotData) {
  const { item, registerBeforeSubmit, reportDirty } = data ?? {};
  const { t } = useTranslation(["nutrition", "common"]);
  const updateNutrition = useUpdateNutrition();
  const [showForm, setShowForm] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [form, setForm] = useState<ProductTemplateNutritionInfo>({});
  // Whether the reader typed since the block opened or was last saved.
  const [touched, setTouched] = useState(false);
  const failure = t("nutritionForm.saveError", {
    defaultValue: "Error saving nutrition",
  });

  // Throws a ReadableError when the product refuses the figures.
  const save = async () => {
    if (!item?.template_id) return;
    const payload = Object.fromEntries(
      Object.entries(form).filter(
        ([, v]) => v !== "" && v !== undefined && v !== null,
      ),
    ) as ProductTemplateNutritionInfo;
    try {
      await updateNutrition.mutateAsync({
        templateId: item.template_id,
        nutritionInfo: payload,
        itemId: item.id,
      });
    } catch (error) {
      throw new ReadableError(extractApiError(error, failure));
    }
    setShowForm(false);
    setTouched(false);
  };

  const latest = useRef({ touched, save });
  latest.current = { touched, save };

  useEffect(() => {
    reportDirty?.(touched);
    return () => reportDirty?.(false);
  }, [touched, reportDirty]);

  useEffect(
    () =>
      registerBeforeSubmit?.(async () => {
        if (latest.current.touched) await latest.current.save();
      }),
    [registerBeforeSubmit],
  );

  const onSave = async () => {
    if (!item?.template_id) return;
    setIsSaving(true);
    try {
      await save();
      toast.success(t("nutritionForm.saved"));
    } catch (error) {
      toast.error(extractApiError(error, failure));
    } finally {
      setIsSaving(false);
    }
  };

  const onToggleForm = () => {
    if (!showForm) {
      // The saved figures, so correcting one does not mean retyping the rest.
      setForm((item && productNutrition(item)) ?? {});
    }
    setTouched(false);
    setShowForm(!showForm);
  };

  const onFieldChange = (
    key: keyof ProductTemplateNutritionInfo,
    value: string,
  ) => {
    setTouched(true);
    setForm((prev) => ({
      ...prev,
      [key]: value === "" ? undefined : Number(value),
    }));
  };

  return { showForm, isSaving, form, onSave, onToggleForm, onFieldChange };
}
