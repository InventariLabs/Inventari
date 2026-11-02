import type { TFunction } from "i18next";

import type { DocumentType } from "@/modules/warehouse/types";

/**
 * What a document type is called where a person picks it: the stock name,
 * with the organization's own label beside it when that adds something.
 *
 * The national presets store bare paperwork codes ("WA", "UML", "PZ"), and
 * the code alone tells a newcomer nothing — so a label never replaces the
 * name. Where the stock name already carries it ("Przyjęcie (PZ)") nothing
 * is repeated.
 */
export function documentTypeName(
  t: TFunction,
  type: DocumentType,
  customLabel?: string | null,
): string {
  const stock = t(`types.${type}`);
  if (!customLabel || stock.includes(customLabel)) return stock;
  return `${stock} (${customLabel})`;
}
