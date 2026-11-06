import { lazy } from "react";
import { Printer } from "lucide-react";
import { moduleRegistry, slotComponent } from "@/lib/moduleRegistry";

const LabelScanPage = lazy(() => import("./pages/LabelScanPage"));
const ItemLabelAttachSlot = lazy(
  () => import("./components/ItemLabelAttachSlot"),
);
const ProductLabelPrintSlot = lazy(
  () => import("./components/ProductLabelPrintSlot"),
);
const ProductLabelSheetHost = lazy(
  () => import("./components/ProductLabelSheetHost"),
);

// A printed QR now opens `/s/<code>` (see the backend's scan_links). The flat
// /labels/scan/:code route stays registered here because the first stickers
// opened exactly that address, and changing it would break labels already
// stuck on shelves.
moduleRegistry.register({
  name: "printing",
  launcher: {
    displayName: "",
    icon: Printer,
    hidden: true,
  },
  routes: [{ path: "/labels/scan/:code", component: LabelScanPage }],
  slots: [
    {
      slot: "item_detail_extra",
      component: slotComponent(ItemLabelAttachSlot),
    },
    {
      slot: "item_detail_extra",
      component: slotComponent(ProductLabelPrintSlot),
    },
    // The sheet the list's bulk action opens. The shell's notice strip is
    // the one slot mounted on every page, and the host draws nothing there
    // until a selection asks for labels.
    {
      slot: "global_notifications",
      component: slotComponent(ProductLabelSheetHost),
    },
  ],
  bulkActions: [
    {
      id: "print-product-labels",
      labelKey: "labels:productLabel.bulkAction",
      icon: Printer,
      // Imported on use: module registration runs on the start path, and
      // the request store is the sheet's, which loads with its host.
      handler: async (itemIds: string[]) => {
        const { useProductLabelRequest } =
          await import("./hooks/useProductLabelRequest");
        useProductLabelRequest.getState().open(itemIds);
      },
    },
  ],
});
