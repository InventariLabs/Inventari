import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { DateInput } from "@/components/ui/DateInput";
import { Input } from "@/components/ui/Input";
import { LazyScanToFill } from "@/modules/shared/components/LazyScanToFill";
import { Sheet, SheetActions, SheetBody } from "@/components/ui/Sheet";

interface Props {
  productName: string | null;
  isLoading: boolean;
  /** Server-side error for the scan — rendered inside this dialog so it is
   * not hidden behind the active view. */
  serverError?: string | null;
  /** Which layer the question takes: "modal" when the page is behind it (the
   * document's execution panel), "modal-nested" when another sheet is (the
   * receiving view). A date popover sits at the modal layer, so a question
   * raised over a nested sheet would hide its own calendar beneath it. */
  zIndex?: "modal" | "modal-nested";
  onConfirm: (batchNumber: string, expiryDate: string) => void;
  onCancel: () => void;
}

/**
 * Asked on the first scan of a product that leaves the shelf by earliest
 * expiry: the scan carries a code and a quantity, so the lot and the date
 * on the pack are read here, once per line. The lot may be absent from a
 * pack; the date may not, because undated stock sorts last under FEFO.
 */
export default function WmsLotExpiryDialog({
  productName,
  isLoading,
  serverError,
  zIndex = "modal-nested",
  onConfirm,
  onCancel,
}: Props) {
  const { t } = useTranslation(["warehouse", "common"]);
  const [batchNumber, setBatchNumber] = useState("");
  const [expiryDate, setExpiryDate] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  // The sheet focuses its first field, and on a phone that raises the
  // keyboard over the expiry date the reader came to fill. The lot is read by
  // the camera as readily as typed, so the title takes the focus instead —
  // this runs after the sheet's own.
  useEffect(() => titleRef.current?.focus(), []);

  const confirm = () => {
    if (!expiryDate) {
      setValidationError(t("receiving.lotExpiry.expiryRequired"));
      return;
    }
    onConfirm(batchNumber.trim(), expiryDate);
  };

  return (
    <Sheet
      open
      onClose={onCancel}
      zIndex={zIndex}
      maxWidth="md"
      aria-label={t("receiving.lotExpiry.title")}
    >
      <SheetBody className="p-5">
        <h3
          ref={titleRef}
          tabIndex={-1}
          className="text-base font-semibold text-on outline-none"
        >
          {t("receiving.lotExpiry.title")}
        </h3>
        <p className="mt-1 text-sm text-on-secondary">
          {productName} — {t("receiving.lotExpiry.hint")}
        </p>

        {(validationError || serverError) && (
          <p
            role="alert"
            className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-800/50 dark:bg-red-950/20 dark:text-red-300"
          >
            {validationError ?? serverError}
          </p>
        )}

        <div className="mt-4 space-y-3">
          <Input
            label={t("receiving.lotExpiry.lot")}
            value={batchNumber}
            onChange={(e) => setBatchNumber(e.target.value)}
            placeholder={t("receiving.lotExpiry.lotPlaceholder")}
            maxLength={100}
          />
          <LazyScanToFill
            label={t("receiving.lotExpiry.scanLot")}
            onCode={(code) => setBatchNumber(code.slice(0, 100))}
          />
          <DateInput
            label={t("receiving.lotExpiry.expiry")}
            required
            value={expiryDate}
            onChange={(value) => {
              setExpiryDate(value);
              setValidationError(null);
            }}
            presets={["plus1Week", "plus1Month", "plus6Months"]}
          />
        </div>

        <SheetActions className="mt-5">
          <Button variant="ghost" onClick={onCancel} disabled={isLoading}>
            {t("common:form.cancel")}
          </Button>
          <Button onClick={confirm} disabled={isLoading} className="gap-1">
            {isLoading && <Loader2 size={14} className="animate-spin" />}
            {t("receiving.lotExpiry.confirm")}
          </Button>
        </SheetActions>
      </SheetBody>
    </Sheet>
  );
}
