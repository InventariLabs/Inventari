import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";

/**
 * Resolve the currency to render for a document / PO / line.
 *
 * Resolution chain: explicit value → organization default → undefined
 * (formatMoney treats undefined as "no currency; locale-formatted number only").
 */
export function useDocumentCurrency(
  documentCurrency?: string | null,
): string | undefined {
  const orgCurrency = useOrganizationCurrency();
  return documentCurrency || orgCurrency || undefined;
}
