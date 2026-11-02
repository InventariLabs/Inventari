import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { extractApiError } from "@/lib/errors";
import { useCompleteProduction } from "@/modules/maker/hooks/useProduction";
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

  const [showConfirm, setShowConfirm] = useState(false);
  const [actualQty, setActualQty] = useState("");
  const [shortages, setShortages] = useState<ShortageEntry[] | null>(null);
  // Whether the refused run was born over stock — recorded by the server at
  // creation, so the dialog says "never enough" when it is true and "ran
  // out since the draft was created" only when that is what happened.
  const [shortAtCreate, setShortAtCreate] = useState<boolean | null>(null);

  function complete() {
    if (!order) return;
    const payload =
      actualQty.trim() !== "" ? { actual_qty: actualQty.trim() } : undefined;

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

  return {
    showConfirm,
    setShowConfirm,
    actualQty,
    setActualQty,
    shortages,
    setShortages,
    shortAtCreate,
    complete,
  };
}
