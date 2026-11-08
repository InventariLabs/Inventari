import { useState } from "react";
import { useTranslation } from "react-i18next";
import i18next from "i18next";
import { FileText, Tag, Trash2, X } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { runWithToast } from "@/lib/api/runWithToast";
import { SendToPrinterButton } from "@/modules/shared/components/SendToPrinterButton";
import { cn } from "@/lib/utils";
import { downloadBlob } from "@/utils/helpers";
import { packingApi, type PackageOut } from "@/modules/warehouse/api/packing";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { QUANTITY_STEP } from "@/hooks/useUomPrecision";

interface Props {
  documentId: string;
  pkg: PackageOut;
  /** Whether scans and taps fill this package. */
  selected: boolean;
  /** False on a completed dispatch, or for a reader who may not write. */
  editable: boolean;
  /** Something is left to pack, so which package fills is worth saying. */
  filling: boolean;
  /** Offer "fill this one" — only when there is another package to choose. */
  selectable: boolean;
  onSelect: () => void;
  onRemoveLine: (lineId: string) => void;
  onWeight: (weightKg: string | null) => void;
  onRemove: () => void;
}

/** The file name the code makes, without the slashes a number carries. */
const fileSafe = (code: string) => code.replace(/[/\s]/g, "-");

/** The weight as typed: no zero padding, nothing for "not weighed". */
const weightText = (weight: string | null | undefined) =>
  weight ? String(Number(weight)) : "";

export function PackageCard({
  documentId,
  pkg,
  selected,
  editable,
  filling,
  selectable,
  onSelect,
  onRemoveLine,
  onWeight,
  onRemove,
}: Props) {
  const { t } = useTranslation("warehouse");
  const [weight, setWeight] = useState(weightText(pkg.weight_kg));
  const [downloading, setDownloading] = useState<"slip" | "label" | null>(null);

  const saveWeight = () => {
    const typed = weight.trim();
    if (typed === weightText(pkg.weight_kg)) return;
    onWeight(typed === "" ? null : typed);
  };

  const download = async (kind: "slip" | "label") => {
    setDownloading(kind);
    await runWithToast(
      async () => {
        if (kind === "slip") {
          const blob = await packingApi.slipPdf(
            documentId,
            pkg.id,
            i18next.language || "en",
          );
          downloadBlob(blob, `packing_slip_${fileSafe(pkg.code)}.pdf`);
        } else {
          const blob = await packingApi.labelPng(documentId, pkg.id);
          downloadBlob(blob, `package_label_${fileSafe(pkg.code)}.png`);
        }
      },
      {
        errorFallback:
          kind === "slip"
            ? t("packing.errors.slipFailed")
            : t("packing.errors.labelFailed"),
      },
    );
    setDownloading(null);
  };

  return (
    <li
      data-testid="package-card"
      className={cn(
        "rounded-xl border p-3 space-y-3",
        selected && filling
          ? "border-primary-500 bg-primary-50/40"
          : "border-border",
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold text-on">{pkg.code}</p>
        {filling && selected && (
          <Badge variant="info">{t("packing.filling")}</Badge>
        )}
        {filling && !selected && selectable && (
          <Button variant="outline" size="sm" onClick={onSelect}>
            {t("packing.fillThis")}
          </Button>
        )}
      </div>

      {pkg.lines.length === 0 ? (
        <p className="text-xs text-on-muted">{t("packing.emptyPackage")}</p>
      ) : (
        <ul className="space-y-1">
          {pkg.lines.map((line) => (
            <li
              key={line.document_line_id}
              className="flex items-center justify-between gap-2 text-sm"
            >
              <span className="min-w-0 truncate text-on">
                {line.product_name ?? t("picking.unknown_product")}
              </span>
              <span className="flex shrink-0 items-center gap-1">
                <span className="tabular-nums text-on-secondary">
                  {formatQuantityLocalized(t, line.quantity, line.uom_symbol)}
                </span>
                {editable && (
                  <Button
                    variant="ghostDanger"
                    size="icon"
                    aria-label={t("packing.removeLine", {
                      product: line.product_name ?? "",
                      code: pkg.code,
                    })}
                    onClick={() => onRemoveLine(line.document_line_id)}
                  >
                    <X size={16} />
                  </Button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}

      {editable ? (
        <Input
          id={`package-weight-${pkg.id}`}
          label={t("packing.weight")}
          type="number"
          inputMode="decimal"
          min={0}
          step={QUANTITY_STEP}
          suffix="kg"
          value={weight}
          onChange={(e) => setWeight(e.target.value)}
          onBlur={saveWeight}
          wrapperClassName="max-w-[12rem]"
        />
      ) : (
        pkg.weight_kg && (
          <p className="text-xs text-on-secondary">
            {t("packing.weight")}: {weightText(pkg.weight_kg)} kg
          </p>
        )
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          leftIcon={<FileText size={16} />}
          isLoading={downloading === "slip"}
          onClick={() => void download("slip")}
        >
          {t("packing.slip")}
        </Button>
        <Button
          variant="outline"
          size="sm"
          leftIcon={<Tag size={16} />}
          isLoading={downloading === "label"}
          onClick={() => void download("label")}
        >
          {t("packing.label")}
        </Button>
        {/* Beside the download, for a packer at a label printer: the same
            label, queued for the print agent. Absent with no printer. */}
        <SendToPrinterButton
          size="sm"
          target={{ packageLabel: { documentId, packageId: pkg.id } }}
        />
        {editable && (
          <>
            {/* Hidden on a phone, where the row wraps and the divider would
                end a line on its own. */}
            <span
              aria-hidden
              className="hidden sm:block w-px h-5 shrink-0 bg-border mx-1"
            />
            <Button
              variant="ghostDanger"
              size="sm"
              leftIcon={<Trash2 size={16} />}
              onClick={onRemove}
            >
              {t("packing.remove")}
            </Button>
          </>
        )}
      </div>
    </li>
  );
}
