import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { Button } from "@/components/ui/Button";
import {
  Sheet,
  SheetActions,
  SheetBody,
  SheetFooter,
  SheetHeader,
} from "@/components/ui/Sheet";
import type { HomeShelfOffer } from "@/modules/warehouse/api/putaway";
import {
  useMakeHomeShelf,
  useSilenceHomeShelf,
} from "@/modules/warehouse/hooks/usePutawayRules";

/** The sentence for an offer; literal keys, so the catalogues' use is traceable. */
function offerSentence(
  t: TFunction<"warehouse">,
  offer: HomeShelfOffer,
  params: Record<string, string>,
): string {
  if (offer.kind === "set") return t("todo.homeShelf.ask.set", params);
  if (offer.kind === "change") return t("todo.homeShelf.ask.change", params);
  switch (offer.reason) {
    case "receiving":
      return t("todo.homeShelf.refused.receiving", params);
    case "quarantine":
      return t("todo.homeShelf.refused.quarantine", params);
    default:
      return t("todo.homeShelf.refused.not_stock", params);
  }
}

/**
 * What a put-away asks once the goods are on a location the rules did not
 * name: whether that location is now the product's home. The answer writes
 * an ordinary put-away rule, so the next delivery of the product is
 * suggested there.
 *
 * A location that cannot be a home (a receiving area, a quarantine location,
 * one that takes no stock) is not offered; the sheet says why instead, so the
 * worker is not left wondering why no question came.
 */
export function HomeShelfPrompt({
  offer,
  isPhone,
  onDone,
}: {
  offer: HomeShelfOffer;
  isPhone: boolean;
  onDone: () => void;
}) {
  const { t } = useTranslation("warehouse");
  const make = useMakeHomeShelf();
  const silence = useSilenceHomeShelf();
  const params = {
    product: offer.product_name ?? "",
    location: offer.location_name ?? "",
  };
  const pending = make.isPending || silence.isPending;

  return (
    <Sheet
      open
      onClose={onDone}
      zIndex="modal"
      maxWidth="sm"
      fullBleedOnMobile={isPhone}
      aria-label={t("todo.homeShelf.title")}
    >
      <SheetHeader title={t("todo.homeShelf.title")} onClose={onDone} />
      <SheetBody className="space-y-3 p-5">
        <p
          className="text-sm text-on"
          role={offer.kind === "refused" ? "status" : undefined}
        >
          {offerSentence(t, offer, params)}
        </p>
        {offer.kind !== "refused" && (
          <Button
            variant="ghost"
            className="w-full whitespace-normal"
            disabled={pending}
            onClick={() =>
              silence.mutate(offer.product_template_id, {
                onSuccess: onDone,
              })
            }
          >
            {t("todo.homeShelf.dontAsk", params)}
          </Button>
        )}
      </SheetBody>
      <SheetFooter>
        <SheetActions>
          {offer.kind === "refused" ? (
            <Button onClick={onDone}>{t("common:actions.close")}</Button>
          ) : (
            <>
              <Button variant="outline" disabled={pending} onClick={onDone}>
                {t("todo.homeShelf.no")}
              </Button>
              <Button
                disabled={pending}
                onClick={() =>
                  make.mutate(
                    {
                      productTemplateId: offer.product_template_id,
                      locationId: offer.location_id,
                    },
                    { onSuccess: onDone },
                  )
                }
              >
                {t("todo.homeShelf.yes")}
              </Button>
            </>
          )}
        </SheetActions>
      </SheetFooter>
    </Sheet>
  );
}
