import { useTranslation } from "react-i18next";
import { CheckSquare, FileDown, FileUp, Tag } from "lucide-react";

import Button from "@/components/ui/Button";
import { Sheet, SheetBody } from "@/components/ui/Sheet";

interface ItemsMobileActionsSheetProps {
  open: boolean;
  /** Whether the account may change products (`items:write`). */
  canWrite: boolean;
  hasRows: boolean;
  onClose: () => void;
  onImport: () => void;
  onExport: () => void;
  onOpenCategories: () => void;
  onSelectItems: () => void;
}

/**
 * The same verbs as the header bar, at phone width.
 *
 * Below `sm` the bar shows one "more" button and everything else lives here,
 * which is why Categories appears in this list and not in the bar: the module
 * nav hides that entry on small screens (`showOnMobile: false`), so this
 * sheet is the only way to it.
 *
 * Selection mode is the only door to the bulk actions below 1024px, and those
 * all write — so it goes with Import when the account may not.
 */
export function ItemsMobileActionsSheet({
  open,
  canWrite,
  hasRows,
  onClose,
  onImport,
  onExport,
  onOpenCategories,
  onSelectItems,
}: ItemsMobileActionsSheetProps) {
  const { t } = useTranslation(["items", "common"]);

  return (
    <Sheet
      open={open}
      onClose={onClose}
      aria-label={t("common:actions.more", { defaultValue: "More actions" })}
    >
      <SheetBody className="flex flex-col gap-2 p-2">
        {canWrite && (
          <Button
            variant="outline"
            onClick={() => {
              onClose();
              onImport();
            }}
            leftIcon={<FileUp size={18} />}
            className="w-full justify-start"
          >
            {t("common:actions.import")}
          </Button>
        )}
        <Button
          variant="outline"
          onClick={() => {
            onClose();
            onExport();
          }}
          disabled={!hasRows}
          leftIcon={<FileDown size={18} className="text-amber-600" />}
          className="w-full justify-start"
        >
          {t("common:actions.export")}
        </Button>
        {!hasRows && (
          <p className="text-sm text-on-muted">
            {t("items:exportNeedsProducts")}
          </p>
        )}
        <Button
          variant="outline"
          onClick={() => {
            onClose();
            onOpenCategories();
          }}
          leftIcon={<Tag size={18} />}
          className="w-full justify-start"
        >
          {t("common:navigation.categories")}
        </Button>
        {canWrite && (
          <Button
            variant="outline"
            onClick={() => {
              onClose();
              onSelectItems();
            }}
            leftIcon={<CheckSquare size={18} />}
            className="w-full justify-start"
          >
            {t("items:actions.selectItems")}
          </Button>
        )}
      </SheetBody>
    </Sheet>
  );
}
