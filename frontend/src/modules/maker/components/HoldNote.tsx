import { useTranslation } from "react-i18next";
import { HELD } from "@/modules/maker/lib/runBatches";
import type { RunBatch } from "@/modules/maker/types/maker";

/**
 * What a held batch says about itself: the word the Batches list uses for its
 * state and the reason typed when it was put on hold. Nothing for a batch
 * that is not held.
 */
export function HoldNote({
  batch,
  className,
}: {
  batch: RunBatch;
  className?: string;
}) {
  const { t } = useTranslation("maker");
  if (!HELD.has(batch.status)) return null;
  const state =
    batch.status === "held"
      ? t("batches.card.state.held")
      : t("batches.card.state.quarantined");
  return (
    <p className={className} data-testid="maker-batch-hold-note">
      {batch.status_reason
        ? t("batches.card.heldBecause", {
            batch: batch.lot_name,
            state,
            reason: batch.status_reason,
          })
        : t("batches.card.heldNoReason", { batch: batch.lot_name, state })}
    </p>
  );
}
