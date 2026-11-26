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

/** The exports being prepared, by the id of the notice each one reports to. */
const preparing = new Set<string>();

/**
 * Runs `work` — a screen's export, from the first notice to the download —
 * unless the export reporting to `toastId` is still being prepared, in which
 * case the click does nothing: that notice is on screen and its file is on the
 * way. A second export would cost the server a second job of the same size.
 * Held outside the screens, so leaving one and coming back changes nothing.
 */
export async function onePreparedAtATime(
  toastId: string,
  work: () => Promise<void>,
): Promise<void> {
  if (preparing.has(toastId)) return;
  preparing.add(toastId);
  try {
    await work();
  } finally {
    preparing.delete(toastId);
  }
}
