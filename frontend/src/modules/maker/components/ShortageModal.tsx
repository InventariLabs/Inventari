import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import type { ShortageEntry } from "@/modules/maker/types/maker";

interface ShortageModalProps {
  open: boolean;
  variant: "warning" | "danger";
  shortages: ShortageEntry[];
  /** When true, shows a confirm button (WARN flow). When false, only close (BLOCK). */
  canConfirm: boolean;
  /** Overrides for the default title/hint (e.g. complete-time shortage). */
  title?: string;
  hint?: string;
  onConfirm?: () => void;
  onCancel: () => void;
  /** A way out offered inside the dialog, under the list (ordering what is missing). */
  action?: ReactNode;
}

export function ShortageModal({
  open,
  variant,
  shortages,
  canConfirm,
  title,
  hint,
  onConfirm,
  onCancel,
  action,
}: ShortageModalProps) {
  const { t } = useTranslation("maker");
  // No quantity is missing when every row is a unit the stock cannot be
  // compared with: the line's unit is what has to be fixed, so the dialog
  // says that instead of asking for a restock.
  const unitMismatchOnly =
    shortages.length > 0 && shortages.every((s) => s.shortage === null);

  return (
    <ConfirmDialog
      open={open}
      variant={variant}
      title={
        unitMismatchOnly
          ? t("availability.unitMismatchTitle")
          : (title ??
            (variant === "danger"
              ? t("availability.blocked")
              : t("availability.warnTitle")))
      }
      message={
        unitMismatchOnly
          ? t("availability.unitMismatchHint")
          : (hint ??
            (variant === "danger"
              ? t("availability.blockedHint")
              : t("availability.warnHint")))
      }
      confirmLabel={t("availability.warnConfirm")}
      cancelLabel={t("create.cancel", { defaultValue: "Cancel" })}
      hideConfirm={!canConfirm}
      onConfirm={onConfirm ?? onCancel}
      onCancel={onCancel}
    >
      <div className="overflow-x-auto" data-testid="shortage-list">
        <p className="text-xs font-medium uppercase tracking-wide text-on-muted pb-1">
          {t("availability.shortageList")}
        </p>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-on-muted border-b border-border">
              <th className="py-2 pr-3">{t("availability.ingredient")}</th>
              <th className="py-2 px-3 text-right">
                {t("availability.needed")}
              </th>
              <th className="py-2 px-3 text-right">
                {t("availability.available")}
              </th>
              <th className="py-2 pl-3 text-right">
                {t("availability.short")}
              </th>
            </tr>
          </thead>
          <tbody>
            {shortages.map((s) => (
              <tr
                key={s.child_template_id}
                className="border-b border-border/50"
              >
                <td className="py-2 pr-3 text-on">
                  {s.child_template_name ?? s.child_template_id}
                  {s.convertible === false && (
                    <span className="block text-xs text-on-warning">
                      {t("availability.notConvertible")}
                    </span>
                  )}
                </td>
                <td className="py-2 px-3 text-right text-on-secondary">
                  {formatQuantityLocalized(t, s.needed, s.uom_symbol)}
                </td>
                <td className="py-2 px-3 text-right text-on-secondary">
                  {/* The stock reading carries the unit it was counted in —
                      labelling litres as kilograms is how "1 g" happened. */}
                  {formatQuantityLocalized(
                    t,
                    s.available,
                    s.convertible === false
                      ? s.available_uom_symbol
                      : s.uom_symbol,
                  )}
                </td>
                <td className="py-2 pl-3 text-right font-semibold text-on-danger">
                  {s.shortage === null ? (
                    <span className="font-normal text-on-muted">
                      {t("availability.shortUnknown")}
                    </span>
                  ) : (
                    formatQuantityLocalized(t, s.shortage, s.uom_symbol)
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {action}
    </ConfirmDialog>
  );
}
