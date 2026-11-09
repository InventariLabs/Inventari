import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { useDebounce } from "@/module-sdk";
import { queryKeys } from "@/hooks/queries/keys";
import { productTemplatesApi } from "@/lib/api/productTemplates";

/** How long the form waits after the last keystroke before asking. */
const SUGGESTION_DELAY_MS = 400;
const SUGGESTION_LIMIT = 5;

interface Props {
  /** The name as typed into the form. */
  name: string;
  /** Put an existing product's exact name into the form. */
  onPick: (name: string) => void;
}

/**
 * The products already in the catalogue whose name contains what is being
 * typed, offered under the name field of a form that creates one.
 *
 * The save attaches the record to an existing product only on its *exact*
 * name, so typing "Wax" while "Soy wax" exists quietly made a second product.
 * Picking a suggestion writes the exact name back, which is the match the
 * save (and the unit hint beside the picker) already understand.
 */
export default function ExistingProductSuggestions({ name, onPick }: Props) {
  const { t } = useTranslation("items");
  const typed = useDebounce(name.trim(), SUGGESTION_DELAY_MS);
  const { data, isError } = useQuery({
    queryKey: queryKeys.inventory.productNameSuggestions(typed),
    enabled: typed.length >= 2,
    staleTime: 60_000,
    queryFn: () => productTemplatesApi.search(typed, SUGGESTION_LIMIT),
  });

  const lowered = typed.toLowerCase();
  // The exact name is the match the save already makes: nothing to offer.
  const others = (data ?? []).filter(
    (product) => product.name.trim().toLowerCase() !== lowered,
  );
  // A hint that could not be fetched is no hint: the save still attaches to
  // an exact name, so the form goes on without it rather than showing an error.
  const offered = !isError && typed.length >= 2 && others.length > 0;

  // The region is always in the page and only its content comes and goes: a
  // live region added together with its text is not reliably announced.
  return (
    <div role="status" aria-live="polite">
      {offered && (
        <div
          className="flex flex-wrap items-center gap-1.5 ml-1"
          data-testid="items-existing-products"
        >
          <span className="text-xs text-on-muted">
            {t("form.existingProducts")}
          </span>
          {others.map((product) => (
            <Button
              key={product.id}
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onPick(product.name)}
            >
              {product.name}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
