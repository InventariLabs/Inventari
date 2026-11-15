import { addDays, format, parseISO } from "date-fns";

/**
 * The best-before a run proposes: the day it was made plus the product's
 * shelf life — the date the server would put on the batch if the person
 * changed nothing. Empty when the product names no shelf life.
 */
export function defaultBestBefore(
  madeOn: string,
  shelfLifeDays: number | null | undefined,
): string {
  if (!madeOn || !shelfLifeDays) return "";
  return format(addDays(parseISO(madeOn), shelfLifeDays), "yyyy-MM-dd");
}
