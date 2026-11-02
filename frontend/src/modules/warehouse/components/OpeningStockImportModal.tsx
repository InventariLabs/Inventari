import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { ImportWizardSheet } from "@/components/import/ImportWizardSheet";
import type { MappingField } from "@/components/import/types";
import { useLocationOffer } from "@/module-sdk";
import { LocationField } from "@/modules/warehouse/components/LocationField";
import { documentsApi } from "@/modules/warehouse/api/documents";
import { useImportOpeningStock } from "@/modules/warehouse/hooks/useDocuments";
import type { OpeningStockImportResponse } from "@/modules/warehouse/types";
import {
  OPENING_STOCK_FIELDS,
  suggestOpeningStockMapping,
} from "./openingStockMapping";

interface Props {
  onClose: () => void;
}

/** Label key per column the importer reads; the line import's own words. */
const LABEL_KEYS: Record<(typeof OPENING_STOCK_FIELDS)[number], string> = {
  name: "import.name",
  sku: "import.sku",
  barcode: "import.barcode",
  quantity: "import.quantity",
  uom_symbol: "import.uom",
  unit_price: "import.unitPrice",
  batch_number: "import.batchNumber",
  expiry_date: "import.expiryDate",
};

/**
 * A whole stock sheet becomes one draft receipt flagged as opening stock.
 * The reader picks where the goods stand, maps the columns, and gets the
 * draft to review and post — every price then lands in the cost layers.
 */
export default function OpeningStockImportModal({ onClose }: Props) {
  const { t } = useTranslation(["warehouse", "common"]);
  const navigate = useNavigate();
  const importMutation = useImportOpeningStock();
  const [targetLocationId, setTargetLocationId] = useState("");
  // The target picker is a stock flow's: goods going into a module's
  // location are that module's workflow, whatever the general lists mix. It
  // searches the places on the server; what is read up front is how many
  // there are, and the first two.
  const { total: placeCount, first: firstPlaces } = useLocationOffer({
    purpose: "stock",
  });
  // One place the goods may stand is no decision: with a single eligible
  // location the field holds it as soon as the answer arrives, the same
  // answer every other stock flow's picker gives (see the product form and
  // the document form). A field the reader empties comes back — the import
  // needs somewhere to land, and there is nowhere else for it to go.
  useEffect(() => {
    if (placeCount !== 1 || targetLocationId) return;
    setTargetLocationId(firstPlaces[0].id);
  }, [placeCount, firstPlaces, targetLocationId]);

  const fields: MappingField[] = OPENING_STOCK_FIELDS.map((key) => ({
    key,
    label: t(LABEL_KEYS[key]),
    required: key === "name",
  }));

  const openDraft = (id: string) => {
    onClose();
    navigate(`/warehouse/documents/${id}`);
  };

  return (
    <ImportWizardSheet<OpeningStockImportResponse>
      onClose={onClose}
      title={t("openingStock.title")}
      formats={t("openingStock.formats")}
      fields={fields}
      requiredField="name"
      canRun={targetLocationId !== ""}
      analyze={(file) => documentsApi.analyzeImportSheet(file)}
      suggest={suggestOpeningStockMapping}
      run={(file, mapping) =>
        importMutation.mutateAsync({ file, mapping, targetLocationId })
      }
      texts={{
        analyzeFailed: t("import.analyzeError"),
        importFailed: t("openingStock.failed"),
        wait: t("openingStock.pleaseWait"),
        added: (count) => t("openingStock.added", { count }),
        closeAndView: t("common:actions.close"),
      }}
      mappingExtras={() => (
        <div className="px-2 space-y-4">
          {/* Where the goods stand, and what the draft will and will not do. */}
          <p className="text-sm text-on-secondary">{t("openingStock.note")}</p>
          <div className="max-w-md">
            <LocationField
              label={t("openingStock.targetLocation")}
              required
              title={t("openingStock.targetLocation")}
              value={targetLocationId}
              onChange={setTargetLocationId}
              placeholder={t("openingStock.targetLocationPlaceholder")}
              searchPlaceholder={t("common:actions.search")}
            />
          </div>
        </div>
      )}
      resultExtras={(result) =>
        result.document_id ? (
          <div className="bg-surface p-6 rounded-xl border border-border max-w-md mx-auto space-y-3">
            <p className="text-sm text-on">
              {t("openingStock.draftReady", { number: result.number })}
            </p>
            {result.stubs_created > 0 && (
              <p className="text-xs text-on-secondary">
                {t("openingStock.stubsCreated", {
                  count: result.stubs_created,
                })}
              </p>
            )}
            <Button
              onClick={() => openDraft(result.document_id as string)}
              rightIcon={<ArrowRight size={16} />}
            >
              {t("openingStock.openDraft")}
            </Button>
          </div>
        ) : (
          <p className="text-sm text-on-secondary max-w-md mx-auto">
            {t("openingStock.nothingLanded")}
          </p>
        )
      }
    />
  );
}
