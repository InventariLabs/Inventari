import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import type { PickingScanResponse } from "@/modules/recipes/types/core";
import { formatDate } from "@/utils/helpers";
import {
  quantityText,
  usePartialPackage,
} from "@/modules/shared/hooks/usePartialPackage";

type Candidate = NonNullable<PickingScanResponse["candidates"]>[number];

/**
 * How much a candidate pack holds. A pack at 0.75 pcs on a 2 kg card reads
 * "1.5 kg left of 2 kg"; everything else keeps the quantity in its unit.
 */
function CandidateQuantity({
  candidate,
  fallbackSymbol,
}: {
  candidate: Candidate;
  fallbackSymbol?: string | null;
}) {
  const { t } = useTranslation(["recipes", "common"]);
  const partial = usePartialPackage()({
    quantity: candidate.quantity,
    uomId: candidate.uom_id,
    pieceMeasure:
      candidate.piece_measure_value && candidate.piece_measure_symbol
        ? {
            value: candidate.piece_measure_value,
            symbol: candidate.piece_measure_symbol,
          }
        : null,
  });
  return (
    <>
      {quantityText(
        t,
        {
          quantity: candidate.quantity,
          uom: { symbol: candidate.uom_symbol ?? fallbackSymbol },
        },
        partial,
      )}
    </>
  );
}

function CandidateButton({
  candidate,
  fallbackSymbol,
  onChoose,
}: {
  candidate: Candidate;
  fallbackSymbol?: string | null;
  onChoose: (itemId: string) => void;
}) {
  const { t } = useTranslation(["recipes"]);
  return (
    <Button
      size="content"
      variant="ghost"
      onClick={() => onChoose(candidate.item_id)}
      className="w-full flex-col items-stretch justify-start px-4 py-3 rounded-xl border border-border hover:border-primary-400 hover:bg-primary-50 active:bg-primary-50"
    >
      <div className="flex justify-between items-center">
        <span className="font-medium text-sm text-on">
          <CandidateQuantity
            candidate={candidate}
            fallbackSymbol={fallbackSymbol}
          />
        </span>
        <span className="flex items-center gap-1">
          {candidate.opened && (
            <Badge variant="warning" className="text-xs">
              {t("picking.scan_result.candidate_opened")}
            </Badge>
          )}
          {candidate.recommended && (
            <Badge variant="success" className="text-xs">
              {t("picking.fefo_badge")}
            </Badge>
          )}
        </span>
      </div>
      {candidate.location && (
        <p className="text-xs text-on-secondary mt-0.5">{candidate.location}</p>
      )}
      {candidate.expiry_date && (
        <p className="text-xs text-on-muted mt-0.5">{candidate.expiry_date}</p>
      )}
      {candidate.opened_at && (
        <p className="text-xs text-on-muted mt-0.5">
          {t("picking.scan_result.candidate_opened_on", {
            date: formatDate(candidate.opened_at),
          })}
        </p>
      )}
    </Button>
  );
}

/**
 * The packs a scan could mean — the same product on two shelves, or an open
 * pack beside a sealed one that expires earlier. The recommended pack is the
 * one the cook would be sent to; the cook may choose another.
 */
export function DisambiguationOverlay({
  scanResult,
  onChoose,
  onCancel,
}: {
  scanResult: PickingScanResponse;
  onChoose: (itemId: string) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation(["recipes", "common"]);
  const candidates = scanResult.candidates ?? [];
  const opensAgainstSealed =
    candidates.some((c) => c.opened) && candidates.some((c) => !c.opened);
  return (
    <div className="flex flex-col h-full p-5">
      <div className="shrink-0 mb-1">
        <p className="text-base font-semibold text-on">
          {t("picking.scan_result.disambiguation")}
        </p>
        <p className="text-sm text-on-secondary mt-0.5">
          {scanResult.ingredient_name}
        </p>
        {opensAgainstSealed && (
          <p className="text-xs text-on-muted mt-1">
            {t("picking.scan_result.open_versus_sealed_hint")}
          </p>
        )}
      </div>
      <div className="flex-1 overflow-y-auto space-y-2 mt-3">
        {candidates.map((c) => (
          <CandidateButton
            key={c.item_id}
            candidate={c}
            fallbackSymbol={scanResult.uom_symbol}
            onChoose={onChoose}
          />
        ))}
      </div>
      <div className="shrink-0 mt-3">
        <Button variant="outline" onClick={onCancel} className="w-full">
          {t("common:form.cancel")}
        </Button>
      </div>
    </div>
  );
}
