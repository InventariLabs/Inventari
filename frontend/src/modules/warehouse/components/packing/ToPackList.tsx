import { useTranslation } from "react-i18next";
import { CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import type { PackingLineOut } from "@/modules/warehouse/api/packing";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";

interface Props {
  /** The lines with something picked and not packed yet. */
  lines: PackingLineOut[];
  /** Whether any package stands — "everything is packed" needs one. */
  packed: boolean;
  /** Tapping a line packs it; absent for a reader who may not write. */
  onTap?: (line: PackingLineOut) => void;
}

/** What is still to pack, each line a tap away from its quantity sheet. */
export function ToPackList({ lines, packed, onTap }: Props) {
  const { t } = useTranslation("warehouse");

  if (lines.length === 0) {
    return packed ? (
      <p className="flex items-center gap-2 text-sm text-success-700">
        <CheckCircle2 size={16} aria-hidden="true" />
        {t("packing.allPacked")}
      </p>
    ) : null;
  }

  return (
    <section aria-labelledby="packing-to-pack" className="space-y-1">
      <h3
        id="packing-to-pack"
        className="text-[10px] font-medium uppercase tracking-widest text-on-muted"
      >
        {t("packing.toPack")}
      </h3>
      <ul className="divide-y divide-border rounded-xl border border-border">
        {lines.map((line) => {
          const text = (
            <>
              <span className="min-w-0 flex-1 truncate text-on">
                {line.product_name ?? t("picking.unknown_product")}
              </span>
              <span className="shrink-0 tabular-nums text-on-secondary">
                {t("packing.leftToPack", {
                  amount: formatQuantityLocalized(
                    t,
                    line.remaining_quantity,
                    line.uom_symbol,
                  ),
                })}
              </span>
            </>
          );
          return (
            <li key={line.document_line_id}>
              {onTap ? (
                <Button variant="ghost" size="row" onClick={() => onTap(line)}>
                  {text}
                </Button>
              ) : (
                <div className="flex gap-3 px-3 py-3 text-sm">{text}</div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
