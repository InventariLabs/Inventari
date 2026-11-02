import { useTranslation } from "react-i18next";
import { FileDown, FileUp, MoreVertical, Plus } from "lucide-react";

import Button from "@/components/ui/Button";

interface ItemsHeaderActionsProps {
  selectionMode: boolean;
  /** Whether the account may change products (`items:write`). */
  canWrite: boolean;
  /** Export is offered over rows, so it has nothing to do over none. */
  hasRows: boolean;
  onExitSelectionMode: () => void;
  onOpenMobileActions: () => void;
  onImport: () => void;
  onExport: () => void;
  onAddProduct: () => void;
}

/**
 * The list's own verbs, lifted out of the page.
 *
 * Not for tidiness: `ItemsPage` sits against the complexity ceiling — the
 * query builder above it was moved out for the same reason — and asking who
 * is looking adds branches wherever the answer is used. Here they are next
 * to the buttons they decide about.
 *
 * Import and Add change the catalogue and need `items:write`. Export reads
 * it, so a read-only account keeps it. Categories is a link and lives in the
 * mobile sheet only, because the module nav already carries it on this screen.
 */
export function ItemsHeaderActions({
  selectionMode,
  canWrite,
  hasRows,
  onExitSelectionMode,
  onOpenMobileActions,
  onImport,
  onExport,
  onAddProduct,
}: ItemsHeaderActionsProps) {
  const { t } = useTranslation(["items", "common"]);

  if (selectionMode) {
    // In selection mode the header's only job is to offer the way out.
    return (
      <div className="flex w-full sm:w-auto items-center justify-end gap-2">
        <Button variant="outline" onClick={onExitSelectionMode}>
          {t("common:actions.cancel")}
        </Button>
      </div>
    );
  }

  return (
    <div className="flex w-full sm:w-auto items-center justify-end gap-2">
      {/* Mobile: overflow menu for secondary actions */}
      <Button
        variant="ghost"
        size="icon"
        onClick={onOpenMobileActions}
        className="sm:hidden"
        aria-label={t("common:actions.more", { defaultValue: "More" })}
      >
        <MoreVertical size={16} />
      </Button>
      {canWrite && (
        <Button
          variant="outline"
          onClick={onImport}
          leftIcon={<FileUp size={16} />}
          className="hidden sm:flex"
        >
          {t("common:actions.import")}
        </Button>
      )}
      {/* A disabled button takes no pointer events, so the reason rides on
          the wrapper. */}
      <span
        title={hasRows ? undefined : t("items:exportNeedsProducts")}
        className="hidden sm:flex"
      >
        <Button
          variant="outline"
          onClick={onExport}
          disabled={!hasRows}
          leftIcon={<FileDown size={16} className="text-amber-600" />}
          aria-describedby={hasRows ? undefined : "export-disabled-reason"}
        >
          {t("common:actions.export")}
        </Button>
        {!hasRows && (
          <span id="export-disabled-reason" className="sr-only">
            {t("items:exportNeedsProducts")}
          </span>
        )}
      </span>
      {/* UI_GUIDELINES §11.3: never wrap the CTA in <Link>. */}
      {canWrite && (
        <Button
          onClick={onAddProduct}
          leftIcon={<Plus size={16} />}
          className="whitespace-nowrap"
        >
          {t("items:addProduct")}
        </Button>
      )}
    </div>
  );
}
