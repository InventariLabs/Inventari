import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
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
import { offerSentence } from "./HomeShelfPrompt";

/**
 * What a receipt in one step asks once it is posted: for each product whose
 * line was put on a shelf other than the suggested one, whether that shelf is
 * now the product's home. A receipt of several such lines asks in this one
 * sheet; an answered row leaves it, and the sheet closes with the last one.
 * A shelf that cannot be a home is told in the row, with its reason, and
 * leaves with the sheet.
 */
export function HomeShelvesSheet({
  offers,
  isPhone = false,
  onDone,
}: {
  offers: HomeShelfOffer[];
  isPhone?: boolean;
  onDone: () => void;
}) {
  const { t } = useTranslation("warehouse");
  const make = useMakeHomeShelf();
  const silence = useSilenceHomeShelf();
  const [open, setOpen] = useState(offers);
  const pending = make.isPending || silence.isPending;

  const settle = (offer: HomeShelfOffer) => {
    const rest = open.filter(
      (row) => row.product_template_id !== offer.product_template_id,
    );
    setOpen(rest);
    if (rest.every((row) => row.kind === "refused")) onDone();
  };

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
      <SheetBody className="space-y-4 p-5">
        {open.map((offer) => {
          const params = {
            product: offer.product_name ?? "",
            location: offer.location_name ?? "",
          };
          return (
            <section
              key={offer.product_template_id}
              className="space-y-2"
              aria-label={params.product}
            >
              <p
                className="text-sm text-on"
                role={offer.kind === "refused" ? "status" : undefined}
              >
                {offerSentence(t, offer, params)}
              </p>
              {offer.kind !== "refused" && (
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    disabled={pending}
                    aria-label={`${t("todo.homeShelf.yes")}: ${params.product}`}
                    onClick={() =>
                      make.mutate(
                        {
                          productTemplateId: offer.product_template_id,
                          locationId: offer.location_id,
                        },
                        {
                          onSuccess: () => {
                            toast.success(t("todo.homeShelf.done", params));
                            settle(offer);
                          },
                        },
                      )
                    }
                  >
                    {t("todo.homeShelf.yes")}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={pending}
                    aria-label={`${t("todo.homeShelf.no")}: ${params.product}`}
                    onClick={() => settle(offer)}
                  >
                    {t("todo.homeShelf.no")}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="whitespace-normal"
                    disabled={pending}
                    onClick={() =>
                      silence.mutate(offer.product_template_id, {
                        onSuccess: () => settle(offer),
                      })
                    }
                  >
                    {t("todo.homeShelf.dontAsk", params)}
                  </Button>
                </div>
              )}
            </section>
          );
        })}
      </SheetBody>
      <SheetFooter>
        <SheetActions>
          <Button variant="outline" onClick={onDone}>
            {t("common:actions.close")}
          </Button>
        </SheetActions>
      </SheetFooter>
    </Sheet>
  );
}
