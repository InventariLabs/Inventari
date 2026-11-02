import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { Sheet, SheetBody, SheetHeader } from "@/components/ui/Sheet";
import { formatDate } from "@/utils/formatters";
import type { Item } from "@/types";
import type { StockTakeItem } from "../types/stock-takes";

interface Props {
  rows: StockTakeItem[];
  getItemById: (itemId: string) => Item | undefined;
  onChoose: (itemId: string) => void;
  onClose: () => void;
}

/**
 * One code, several rows of this count: the same product on two shelves, or
 * in two batches. The scan cannot tell them apart, so the reader picks the
 * one in their hand. A row is told apart by where it stands and when it
 * expires — never by its expected quantity, which blind mode keeps hidden.
 */
export default function StockTakeScanChooser({
  rows,
  getItemById,
  onChoose,
  onClose,
}: Props) {
  const { t } = useTranslation(["stock_takes"]);
  return (
    <Sheet
      open={rows.length > 0}
      onClose={onClose}
      maxWidth="md"
      aria-labelledby="stock-take-scan-chooser-title"
    >
      <SheetHeader onClose={onClose}>
        <h2
          id="stock-take-scan-chooser-title"
          className="text-lg font-semibold text-on"
        >
          {t("scan.chooseTitle")}
        </h2>
      </SheetHeader>
      <SheetBody className="p-3">
        <p className="px-2 pb-2 text-sm text-on-secondary">
          {t("scan.chooseHint")}
        </p>
        {rows.map((row) => {
          const expiry = getItemById(row.item_id ?? "")?.effective_expiry_date;
          return (
            <Button
              key={row.id}
              size="content"
              variant="ghost"
              onClick={() => onChoose(row.item_id!)}
              className="w-full justify-start py-3 text-left rounded-lg"
            >
              <span className="flex flex-col items-start">
                <span className="font-medium">{row.item_name}</span>
                <span className="text-sm text-on-secondary">
                  {row.shelf_location && <span>{row.shelf_location}</span>}
                  {expiry && (
                    <span>
                      {row.shelf_location && " • "}
                      {t("scan.expires", { date: formatDate(expiry) })}
                    </span>
                  )}
                </span>
              </span>
            </Button>
          );
        })}
      </SheetBody>
    </Sheet>
  );
}
