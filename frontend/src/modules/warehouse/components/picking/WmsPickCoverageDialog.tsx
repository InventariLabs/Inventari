import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import {
  Sheet,
  SheetActions,
  SheetBody,
  SheetFooter,
  SheetHeader,
} from "@/components/ui/Sheet";
import type { WmsPickUncoveredDocument } from "@/modules/warehouse/api/documents_picking";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";

interface Props {
  /** The dispatches stock cannot cover, each with the lines that are short. */
  documents: WmsPickUncoveredDocument[];
  /** Whether other dispatches remain to be picked without these. */
  canLeaveOut: boolean;
  onStartAnyway: () => void;
  onLeaveOut: () => void;
  onClose: () => void;
}

/**
 * What a pick walk will come back short on, said before it starts.
 *
 * The person decides here, not at the shelf: start without the documents
 * stock cannot cover, or start with them anyway. Closing the sheet starts
 * nothing.
 */
export default function WmsPickCoverageDialog({
  documents,
  canLeaveOut,
  onStartAnyway,
  onLeaveOut,
  onClose,
}: Props) {
  const { t } = useTranslation("warehouse");
  return (
    <Sheet
      open
      onClose={onClose}
      maxWidth="md"
      aria-label={t("picking.coverage.title")}
    >
      <SheetHeader title={t("picking.coverage.title")} onClose={onClose} />
      <SheetBody className="space-y-4 p-5">
        <p className="text-sm text-on-secondary">
          {t("picking.coverage.intro")}
        </p>
        {documents.map((doc) => (
          <section key={doc.document_id}>
            <h3 className="text-sm font-semibold text-on">
              {doc.document_number}
            </h3>
            <ul className="mt-1 space-y-1 text-sm text-on-secondary">
              {doc.lines.map((line, index) => (
                <li key={index}>
                  {t("picking.coverage.line", {
                    product: line.product_name ?? t("picking.unknown_product"),
                    ordered: formatQuantityLocalized(
                      t,
                      line.ordered,
                      line.uom_symbol,
                    ),
                    available: formatQuantityLocalized(
                      t,
                      line.available,
                      line.uom_symbol,
                    ),
                  })}
                </li>
              ))}
            </ul>
          </section>
        ))}
      </SheetBody>
      <SheetFooter>
        <SheetActions>
          {canLeaveOut ? (
            <>
              <Button variant="outline" onClick={onStartAnyway}>
                {t("picking.coverage.start_anyway")}
              </Button>
              <Button onClick={onLeaveOut}>
                {t("picking.coverage.leave_out")}
              </Button>
            </>
          ) : (
            <Button onClick={onStartAnyway}>
              {t("picking.coverage.start_anyway")}
            </Button>
          )}
        </SheetActions>
      </SheetFooter>
    </Sheet>
  );
}
