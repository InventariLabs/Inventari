import type { TFunction } from "i18next";
import { toast } from "sonner";
import type { ExportProgress } from "@/lib/api/items";

/**
 * The listener a screen hands to `itemsApi.exportXlsx`: it turns the notice
 * the export opened under `toastId` into "Preparing the export: N%" while a
 * long sheet is written in the background. `t` is any translator; the key
 * names its namespace.
 */
export function showExportProgress(
  t: TFunction,
  toastId: string,
): (progress: ExportProgress) => void {
  return ({ percent }) => {
    toast.loading(t("common:actions.exportPreparing", { percent }), {
      id: toastId,
    });
  };
}
