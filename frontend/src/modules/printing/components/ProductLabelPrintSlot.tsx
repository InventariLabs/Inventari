import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Printer } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { productCode, itemSku, type Item } from "@/types";
import { BarcodeLabelSheet } from "@/modules/shared/components/BarcodeLabelSheet";

/**
 * The product page's "Print label": the product's name and its code in bars.
 * Only for a product that has a code — one without gets it on its form first.
 */
export default function ProductLabelPrintSlot({
  data,
}: {
  data: { item: Item };
}) {
  const { t } = useTranslation("labels");
  const [open, setOpen] = useState(false);
  const { item } = data;

  if (!productCode(item) && !itemSku(item)) return null;

  return (
    <>
      <Button
        variant="outline"
        onClick={() => setOpen(true)}
        leftIcon={<Printer size={16} />}
      >
        {t("productLabel.action")}
      </Button>
      {open && (
        <BarcodeLabelSheet
          target={{ itemIds: [item.id] }}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}
