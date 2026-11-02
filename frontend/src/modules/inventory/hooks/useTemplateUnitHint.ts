import { useQuery } from "@tanstack/react-query";
import { useDebounce } from "@/module-sdk";
import { queryKeys } from "@/hooks/queries/keys";
import { lookupProduct } from "@/modules/shared/lib/productLookup";

/** How long the form waits after the last keystroke before asking. */
const TEMPLATE_HINT_DELAY_MS = 400;

/** The product template the name or barcode would land on, if the catalogue
 * has one — the unit it keeps travels with it. */
export interface TemplateUnitHint {
  templateId: string;
  /** The matched product's name, which is not always the typed one. */
  productName: string;
  uomId: string;
  /** The unit's symbol (`kg`), and its name (`Kilogram`). */
  uomSymbol: string;
  uomName: string;
}

/**
 * Which unit the catalogue will count this product in.
 *
 * Asked of the same endpoint the create path resolves its template through,
 * and with the same fields the form will submit, so the hint shown before a
 * save and the unit the record lands with are one answer rather than two.
 * Naming the unit in a form used to be a guess: the picker said whatever the
 * reader left in it, and the backend then settled the record's unit itself.
 */
export function useTemplateUnitHint(
  name: string | undefined,
  barcode: string | undefined,
): {
  hint: TemplateUnitHint | null;
  /** The catalogue could not be asked: no hint is not "no template". */
  failed: boolean;
  retry: () => void;
} {
  const debouncedName = useDebounce(
    (name ?? "").trim(),
    TEMPLATE_HINT_DELAY_MS,
  );
  const trimmedBarcode = (barcode ?? "").trim();
  const enabled = trimmedBarcode.length > 0 || debouncedName.length >= 2;

  const { data, isError, refetch } = useQuery({
    queryKey: queryKeys.inventory.templateUnitHint(
      trimmedBarcode,
      debouncedName,
    ),
    enabled,
    staleTime: 60_000,
    queryFn: async () => {
      const result = await lookupProduct({
        ...(trimmedBarcode ? { barcode: trimmedBarcode } : {}),
        ...(debouncedName ? { name: debouncedName } : {}),
      });
      // An OFF answer is knowledge about the packaging, not a catalogue row
      // this organization keeps, so there is no template unit to hold the
      // record to and nothing to hint at.
      if (
        !result?.product_template_id ||
        !result.uom_id ||
        !result.uom_symbol
      ) {
        return null;
      }
      return {
        templateId: result.product_template_id,
        productName: result.name,
        uomId: result.uom_id,
        uomSymbol: result.uom_symbol,
        uomName: result.uom_name ?? result.uom_symbol,
      } satisfies TemplateUnitHint;
    },
  });

  return { hint: data ?? null, failed: isError, retry: () => void refetch() };
}
