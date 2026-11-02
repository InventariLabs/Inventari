import { useState } from "react";
import { useTranslation } from "react-i18next";
import { QrCode } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { useCanWrite } from "@/hooks/useCanWrite";
import { AttachLabelToExistingItemSheet } from "@/modules/printing/components/AttachLabelToExistingItemSheet";
import type { Item } from "@/types";

/**
 * The product page's way to put a pool sticker on a product that is already
 * entered — the printing module's contribution to `item_detail_extra`.
 * A product that has a label keeps it: binding another would free the first.
 */
export default function ItemLabelAttachSlot({
  data,
}: {
  data: { item: Item };
}) {
  const { t } = useTranslation("labels");
  const canWrite = useCanWrite("items");
  const [open, setOpen] = useState(false);
  const { item } = data;

  if (!canWrite || item.label_code) return null;

  return (
    <>
      <Button
        variant="outline"
        onClick={() => setOpen(true)}
        leftIcon={<QrCode size={16} />}
      >
        {t("attachToItem.itemAction")}
      </Button>
      {open && (
        <AttachLabelToExistingItemSheet
          item={item}
          onClose={() => setOpen(false)}
          onAttached={() => setOpen(false)}
        />
      )}
    </>
  );
}
