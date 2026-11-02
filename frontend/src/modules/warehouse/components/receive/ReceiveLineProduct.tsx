import { useState } from "react";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { ProductQuickCreateSearch } from "@/modules/shared/components/ProductQuickCreateSearch";
import {
  createProductTemplate,
  searchProductTemplates,
} from "@/lib/api/productTemplateOptions";
import type { ReceiveDraftLine } from "./receiveDraft";

interface Props {
  line: ReceiveDraftLine;
  canWrite: boolean;
  onUpdate: (key: string, patch: Partial<ReceiveDraftLine>) => void;
}

/**
 * The product an order line typed by hand arrives as.
 *
 * Stock takes only catalogue products, and which product the buyer's words
 * mean — one on the list, or a new one with its unit — is for the person
 * receiving it to say; the receipt does not guess it from the name. The
 * search opens on the line's own name, so a match or the offer to add it is
 * there without typing. Rows that came with a product show nothing here.
 */
export function ReceiveLineProduct({ line, canWrite, onUpdate }: Props) {
  const { t } = useTranslation("warehouse");
  const [picking, setPicking] = useState(false);
  const typedOrderLine =
    line.sourcePoLineId !== null &&
    (line.productTemplateId === null || line.chosenProductName !== null);
  if (!typedOrderLine) return null;

  const question = t("receive.whichProduct", { name: line.name });
  if (line.chosenProductName !== null) {
    return (
      <div className="flex items-center gap-1 text-xs text-on-secondary">
        <span className="truncate">
          {t("receive.chosenProduct", { name: line.chosenProductName })}
        </span>
        <Button
          variant="ghost"
          size="iconSm"
          disabled={!canWrite}
          onClick={() =>
            onUpdate(line.key, {
              productTemplateId: null,
              chosenProductName: null,
            })
          }
          aria-label={question}
          title={question}
        >
          <X size={14} />
        </Button>
      </div>
    );
  }
  if (!picking) {
    return (
      <Button
        variant="link"
        size="content"
        className="min-h-11 px-0 py-2 text-left text-xs md:min-h-10"
        disabled={!canWrite}
        onClick={() => setPicking(true)}
      >
        {question}
      </Button>
    );
  }
  return (
    <div className="mt-1 w-64">
      <ProductQuickCreateSearch
        search={searchProductTemplates}
        createProduct={createProductTemplate}
        onSelect={(picked) => {
          setPicking(false);
          onUpdate(line.key, {
            productTemplateId: picked.product_template_id,
            chosenProductName: picked.name,
          });
        }}
        label={question}
        testId={`receive-line-product-${line.key}`}
        initialQuery={line.name}
        defaultUomId={line.uomId}
      />
    </div>
  );
}
