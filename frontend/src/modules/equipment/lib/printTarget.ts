import type { PrintTarget } from "@/modules/shared/lib/printQueue";

/**
 * The selected assets' labels, as something to send to a printer — or null
 * when none of them carries a label code yet.
 */
export function selectedLabelTarget(
  items: { id: string; label_code?: string | null }[],
  selectedIds: Set<string>,
): PrintTarget | null {
  const shortCodes = items
    .filter((item) => selectedIds.has(item.id) && item.label_code)
    .map((item) => item.label_code as string);
  return shortCodes.length > 0 ? { shortCodes } : null;
}
