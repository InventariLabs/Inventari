import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { DateInput } from "@/components/ui/DateInput";
import { Input } from "@/components/ui/Input";
import {
  Sheet,
  SheetActions,
  SheetBody,
  SheetFooter,
  SheetHeader,
} from "@/components/ui/Sheet";
import { extractApiError } from "@/lib/errors";
import { formatQuantityLocalized, unitLabel } from "@/lib/i18nHelpers";
import type { PieceMeasure } from "@/utils/partialPackage";

/** What the person said is left: nothing named means only "opened". */
export interface LeftAmount {
  left?: number;
  leftUomId?: string;
  /** A day (YYYY-MM-DD) after which the opened package should not be used. */
  useBy?: string;
}

interface Props {
  itemName: string;
  /** What one piece measures; null when the card cannot say what is left. */
  measure: PieceMeasure | null;
  packCounted?: boolean;
  onSubmit: (amount: LeftAmount) => Promise<void>;
  onClose: () => void;
}

/**
 * "How much is left?" for a package that has just been opened.
 *
 * The question is what is LEFT, not what was used: it is what a person sees
 * looking at the bag, and saying it twice cannot take the amount off twice.
 * Where the card records what one piece weighs or holds, the answer is a
 * share of it or a number in that unit; where it does not, the only honest
 * things to record are that the package is open or that it is finished.
 */
export default function PartlyUsedSheet({
  itemName,
  measure,
  packCounted = false,
  onSubmit,
  onClose,
}: Props) {
  const { t } = useTranslation(["labels", "common"]);
  const [typed, setTyped] = useState("");
  const [useBy, setUseBy] = useState("");
  const [busy, setBusy] = useState(false);

  const send = async (amount: LeftAmount) => {
    setBusy(true);
    try {
      await onSubmit(useBy ? { ...amount, useBy } : amount);
      onClose();
    } catch (error) {
      // The sheet stays open with the choice still on it, and the refusal
      // is said here: the button awaiting `send` reads nothing.
      toast.error(extractApiError(error, t("common:errors.actionFailed")));
    } finally {
      setBusy(false);
    }
  };

  const typedValue = Number(typed.replace(",", "."));
  const typedValid =
    measure !== null &&
    typed.trim() !== "" &&
    Number.isFinite(typedValue) &&
    typedValue >= 0 &&
    typedValue <= measure.value;
  const unit = measure ? unitLabel(t, measure.symbol) : "";
  // The quick choices, as shares of one piece.
  const quickShares = [
    { share: 0.75, label: t("stockActions.quarter3") },
    { share: 0.5, label: t("stockActions.half") },
    { share: 0.25, label: t("stockActions.quarter1") },
  ];

  return (
    <Sheet open onClose={onClose} zIndex="modal-nested" aria-label={itemName}>
      <SheetHeader title={t("stockActions.partlyTitle")} onClose={onClose} />
      <SheetBody className="p-5">
        <p className="text-sm text-on-secondary mb-4">{itemName}</p>
        {measure ? (
          <>
            <p className="text-sm text-on-secondary mb-3">
              {t("stockActions.partlyHint", { unit })}
            </p>
            <div className="grid grid-cols-2 items-end gap-2 mb-4">
              {quickShares.map(({ share, label }) => (
                <Button
                  key={share}
                  variant="secondary"
                  disabled={busy}
                  onClick={() =>
                    send({
                      left: Number((share * measure.value).toFixed(4)),
                      leftUomId: measure.uomId,
                    })
                  }
                >
                  {label} ·{" "}
                  {formatQuantityLocalized(
                    t,
                    Number((share * measure.value).toFixed(4)),
                    measure.symbol,
                  )}
                </Button>
              ))}
              <Button
                variant="secondary"
                disabled={busy}
                onClick={() => send({ left: 0 })}
              >
                {t("stockActions.empty")}
              </Button>
            </div>
            <Input
              type="number"
              inputMode="decimal"
              min={0}
              max={measure.value}
              step="any"
              label={t("stockActions.amountLabel", { unit })}
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
            />
          </>
        ) : (
          <p className="text-sm text-on-secondary">
            {t(
              packCounted
                ? "stockActions.partlyPackNoMeasure"
                : "stockActions.partlyNoMeasure",
            )}
          </p>
        )}
        <div className="mt-4">
          <DateInput
            label={t("stockActions.useByLabel")}
            value={useBy}
            onChange={setUseBy}
            presets={["plus1Week", "plus1Month"]}
          />
        </div>
      </SheetBody>
      <SheetFooter>
        <SheetActions>
          {measure ? (
            <Button
              disabled={!typedValid || busy}
              onClick={() =>
                send({ left: typedValue, leftUomId: measure.uomId })
              }
            >
              {t("stockActions.save")}
            </Button>
          ) : (
            <>
              <Button
                variant="secondary"
                disabled={busy}
                onClick={() => send({})}
              >
                {t("stockActions.markOpened")}
              </Button>
              <Button disabled={busy} onClick={() => send({ left: 0 })}>
                {t("stockActions.finished")}
              </Button>
            </>
          )}
        </SheetActions>
      </SheetFooter>
    </Sheet>
  );
}
