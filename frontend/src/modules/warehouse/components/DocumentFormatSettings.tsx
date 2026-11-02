import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { exampleReceiptNumber } from "@/modules/warehouse/lib/exampleNumber";

const SEQ_TOKEN_REGEX = /\{SEQ:0*(\d+)d\}/;

interface DocumentFormatSettingsProps {
  /** The page's whole draft against the saved profile — the dirty
   *  definition lives where the state does, in the composition root. */
  numberingFormat: string;
  numberPadding: number;
  typeLabelIN: string;
  typeLabelOUT: string;
  typeLabelINT: string;
  typeLabelInternalIn: string;
  typeLabelInternalOut: string;
  typeLabelCORR: string;
  typeLabelSCRAP: string;
  typeLabelADJ: string;
  onNumberingFormatChange: (format: string) => void;
  onNumberPaddingChange: (padding: number) => void;
  onTypeLabelINChange: (label: string) => void;
  onTypeLabelOUTChange: (label: string) => void;
  onTypeLabelINTChange: (label: string) => void;
  onTypeLabelInternalInChange: (label: string) => void;
  onTypeLabelInternalOutChange: (label: string) => void;
  onTypeLabelCORRChange: (label: string) => void;
  onTypeLabelSCRAPChange: (label: string) => void;
  onTypeLabelADJChange: (label: string) => void;
}

function rewriteSeqToken(format: string, padding: number): string {
  return format.replace(SEQ_TOKEN_REGEX, `{SEQ:0${padding}d}`);
}

function readSeqToken(format: string): number | null {
  const match = SEQ_TOKEN_REGEX.exec(format);
  if (!match) return null;
  return Number.parseInt(match[1], 10);
}

export function DocumentFormatSettings({
  numberingFormat,
  numberPadding,
  typeLabelIN,
  typeLabelOUT,
  typeLabelINT,
  typeLabelInternalIn,
  typeLabelInternalOut,
  typeLabelCORR,
  typeLabelSCRAP,
  typeLabelADJ,
  onNumberingFormatChange,
  onNumberPaddingChange,
  onTypeLabelINChange,
  onTypeLabelOUTChange,
  onTypeLabelINTChange,
  onTypeLabelInternalInChange,
  onTypeLabelInternalOutChange,
  onTypeLabelCORRChange,
  onTypeLabelSCRAPChange,
  onTypeLabelADJChange,
}: DocumentFormatSettingsProps) {
  const { t } = useTranslation("warehouse");

  const handlePaddingChange = (value: string) => {
    const padding = Number.parseInt(value, 10);
    if (Number.isNaN(padding)) return;
    onNumberPaddingChange(padding);
    if (SEQ_TOKEN_REGEX.test(numberingFormat)) {
      onNumberingFormatChange(rewriteSeqToken(numberingFormat, padding));
    }
  };

  const handleFormatChange = (value: string) => {
    onNumberingFormatChange(value);
    const tokenDigits = readSeqToken(value);
    if (tokenDigits !== null && tokenDigits !== numberPadding) {
      onNumberPaddingChange(tokenDigits);
    }
  };

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-3 items-end gap-4">
        <Input
          label={t("profile.numberingFormat")}
          value={numberingFormat}
          onChange={(e) => handleFormatChange(e.target.value)}
          placeholder="{TYPE}/{YEAR}/{SEQ:03d}"
          className="font-mono text-xs"
        />
        <p className="text-xs text-on-secondary -mt-2 md:col-span-3">
          {t("profile.numberingFormatHint", {
            // Written from the draft as it stands, so the example follows
            // every keystroke and is a number this profile would produce.
            example: exampleReceiptNumber({
              numberingFormat,
              numberPadding,
              receiptLabel: typeLabelIN,
            }),
          })}
        </p>

        <NativeSelect
          label={t("profile.numberPadding")}
          value={String(numberPadding)}
          onChange={(e) => handlePaddingChange(e.target.value)}
        >
          {[3, 4, 5, 6].map((n) => (
            <option key={n} value={n}>
              {t("profile.numberPaddingDigits", { count: n })}
            </option>
          ))}
        </NativeSelect>
      </div>

      <p className="text-xs text-on-secondary">
        {t("profile.numberPaddingSharedHint")}
      </p>

      <div className="space-y-4">
        <p className="text-xs font-medium uppercase text-on-secondary tracking-wide ml-1">
          {t("profile.typeLabels")}
        </p>
        <div className="grid grid-cols-2 items-end md:grid-cols-3 gap-4">
          <Input
            label={t("profile.typeLabelFor", { type: t("types.IN") })}
            value={typeLabelIN}
            onChange={(e) => onTypeLabelINChange(e.target.value)}
            placeholder={t("typesShort.IN")}
          />
          <Input
            label={t("profile.typeLabelFor", { type: t("types.OUT") })}
            value={typeLabelOUT}
            onChange={(e) => onTypeLabelOUTChange(e.target.value)}
            placeholder={t("typesShort.OUT")}
          />
          <Input
            label={t("profile.typeLabelFor", { type: t("types.INT") })}
            value={typeLabelINT}
            onChange={(e) => onTypeLabelINTChange(e.target.value)}
            placeholder={t("typesShort.INT")}
          />
          <Input
            label={t("profile.typeLabelFor", { type: t("types.INTERNAL_IN") })}
            value={typeLabelInternalIn}
            onChange={(e) => onTypeLabelInternalInChange(e.target.value)}
            placeholder={t("typesShort.INTERNAL_IN")}
          />
          <Input
            label={t("profile.typeLabelFor", { type: t("types.INTERNAL_OUT") })}
            value={typeLabelInternalOut}
            onChange={(e) => onTypeLabelInternalOutChange(e.target.value)}
            placeholder={t("typesShort.INTERNAL_OUT")}
          />
          <Input
            label={t("profile.typeLabelFor", { type: t("types.CORRECTION") })}
            value={typeLabelCORR}
            onChange={(e) => onTypeLabelCORRChange(e.target.value)}
            placeholder={t("typesShort.CORRECTION")}
          />
          <Input
            label={t("profile.typeLabelFor", { type: t("types.SCRAP") })}
            value={typeLabelSCRAP}
            onChange={(e) => onTypeLabelSCRAPChange(e.target.value)}
            placeholder={t("typesShort.SCRAP")}
          />
          <Input
            label={t("profile.typeLabelFor", { type: t("types.ADJUSTMENT") })}
            value={typeLabelADJ}
            onChange={(e) => onTypeLabelADJChange(e.target.value)}
            placeholder={t("typesShort.ADJUSTMENT")}
          />
        </div>
      </div>
    </div>
  );
}
