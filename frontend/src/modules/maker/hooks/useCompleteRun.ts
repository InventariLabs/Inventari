import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { extractApiError } from "@/lib/errors";
import { useCompleteProduction } from "@/modules/maker/hooks/useProduction";
import { useBatchChoice } from "@/modules/maker/hooks/useBatchChoice";
import { useProposedBestBefore } from "@/modules/maker/hooks/useProposedBestBefore";
import { todayIso } from "@/utils/formatters";
import {
  parseEmptyBomError,
  parseShortageError,
} from "@/modules/maker/lib/shortageError";
import type {
  ProductionOrder,
  ShortageEntry,
} from "@/modules/maker/types/maker";

/**
 * Completing a production run, with the three answers the server can give.
 *
 * A refusal here is rarely "it failed": it is a shortage list the operator can
 * act on, or a BOM with nothing in it. Both arrive as a 422 carrying their own
 * payload, and both belong to this one action rather than to the page around
 * it — which is why the confirmation state and the typed-in quantity live here
 * too.
 */
export function useCompleteRun(order: ProductionOrder | undefined) {
  const { t } = useTranslation("maker");
  const navigate = useNavigate();
  const completeMutation = useCompleteProduction();

  const [showConfirm, setShowConfirmState] = useState(false);
  const [actualQty, setActualQty] = useState("");
  // The day the goods were made: today until the person names another. The
  // plan's day is where the run was meant to happen, not where it did.
  const [madeOn, setMadeOn] = useState(todayIso());
  // The output batch's best-before, proposed from the day it was made and the
  // product's shelf life; the person may change it.
  const proposed = useProposedBestBefore(madeOn, order?.shelf_life_days);
  const bestBefore = proposed.value;
  const setBestBefore = proposed.set;
  // The batches the ingredients come from — asked only while the dialog is
  // open on a draft, since a closed run has taken its batches already.
  const batchQuery = useMemo(
    () =>
      showConfirm && order && order.status === "DRAFT"
        ? {
            output_template_id: order.output_template_id,
            planned_qty: String(order.planned_qty),
            output_location_id: order.output_location_id,
            recipe_id: order.recipe_id ?? null,
          }
        : null,
    [showConfirm, order],
  );
  const batches = useBatchChoice(batchQuery);

  function setShowConfirm(open: boolean) {
    if (open) {
      setMadeOn(todayIso());
      proposed.reset();
    }
    setShowConfirmState(open);
  }
  const [shortages, setShortages] = useState<ShortageEntry[] | null>(null);
  // Whether the refused run was born over stock — recorded by the server at
  // creation, so the dialog says "never enough" when it is true and "ran
  // out since the draft was created" only when that is what happened.
  const [shortAtCreate, setShortAtCreate] = useState<boolean | null>(null);

  function complete() {
    if (!order) return;
    const payload = {
      ...(actualQty.trim() !== "" && { actual_qty: actualQty.trim() }),
      ...(madeOn && { made_on: madeOn }),
      ...(bestBefore && { best_before: bestBefore }),
      ...(batches.payload.length > 0 && { ingredient_lots: batches.payload }),
    };

    completeMutation.mutate(
      { orderId: order.id, data: payload },
      {
        onSuccess: () => {
          toast.success(t("detail.completeSuccess"));
          setActualQty("");
        },
        onError: (err) => {
          // An actionable shortage list, not a blind generic toast.
          const shortageInfo = parseShortageError(err);
          if (shortageInfo?.error === "insufficient_stock") {
            setShowConfirm(false);
            setShortages(shortageInfo.shortages);
            setShortAtCreate(shortageInfo.shortAtCreate ?? null);
            return;
          }
          // A BOM with no ingredients is refused: the run would create the
          // output against zero consumption. Say so, and offer the one place
          // where it can be fixed.
          const emptyBom = parseEmptyBomError(err);
          if (emptyBom) {
            setShowConfirm(false);
            toast.error(t("detail.emptyBom"), {
              action: emptyBom.recipeId
                ? {
                    label: t("detail.emptyBomAction"),
                    onClick: () =>
                      navigate(`/maker/recipes/${emptyBom.recipeId}`),
                  }
                : undefined,
            });
            return;
          }
          toast.error(extractApiError(err, t("detail.completeFailed")));
        },
      },
    );
  }

  /** A refusal from another door (starting the run) opens the same dialog. */
  function showShortage(entries: ShortageEntry[], born: boolean) {
    setShortages(entries);
    setShortAtCreate(born);
  }

  return {
    showShortage,
    showConfirm,
    setShowConfirm,
    actualQty,
    setActualQty,
    madeOn,
    setMadeOn,
    bestBefore,
    setBestBefore,
    batches,
    shortages,
    setShortages,
    shortAtCreate,
    complete,
  };
}
