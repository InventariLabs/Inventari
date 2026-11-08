import { lazy } from "react";
import i18n from "i18next";
import { toast } from "sonner";
import { ClipboardCopy, Shapes } from "lucide-react";
import { copyTextOrExplain, moduleRegistry } from "@/module-sdk";

const WidgetsPage = lazy(() => import("./pages/WidgetsPage"));

moduleRegistry.register({
  name: "example_widgets",
  routes: [{ path: "/widgets", component: WidgetsPage }],
  // The launcher lists only modules that declare a tile; a module copied from
  // this one without it is switched on and then reachable only by its address.
  launcher: {
    displayName: "modules:modules.example_widgets.name",
    description: "modules:modules.example_widgets.description",
    icon: Shapes,
    color: "bg-blue-500",
    category: "business",
    order: 90,
  },
  moduleNav: {
    basePath: "/widgets",
    items: [
      {
        path: "",
        icon: Shapes,
        labelKey: "example_widgets:navigation.widgets",
      },
    ],
  },
  // Reference implementation of `bulkActions`, the one to copy: the extension
  // point's consumer is ItemsBulkActionBar, and printing contributes the other
  // action in the tree (product labels). Selecting items in inventory shows
  // this one whenever example_widgets is enabled.
  //
  // The handler is given identifiers and nothing else, so the action is named
  // after what it can actually deliver. It used to be "Export selected to CSV",
  // under the Download icon, two rows below the screen's own Export button —
  // one name and one icon for two different results, and the one contributed
  // here handed over a column of UUIDs.
  bulkActions: [
    {
      id: "copy-selected-ids",
      labelKey: "example_widgets:actions.copyIds",
      icon: ClipboardCopy,
      handler: async (itemIds: string[]) => {
        const copied = await copyTextOrExplain(
          itemIds.join("\n"),
          i18n.t("common:copy.failed"),
        );
        if (copied) {
          toast.success(i18n.t("example_widgets:messages.idsCopied"));
        }
      },
    },
  ],
  // Reference implementation of `validationRules`: the accessor existed but no
  // module produced a rule and no form consumed one. This rule really blocks a
  // save — an item named only with digits is almost always a mis-scan landing
  // in the name field.
  //
  // The message names a place that exists. It used to say "scan it into the
  // barcode field", and the form it appears on has no barcode field: advice a
  // reader cannot follow is worse than no advice, because they go looking.
  validationRules: [
    {
      form: "item_create",
      field: "name",
      validator: (value) =>
        typeof value === "string" && /^\d+$/.test(value.trim())
          ? i18n.t("example_widgets:validation.nameLooksLikeBarcode")
          : null,
    },
  ],
});
