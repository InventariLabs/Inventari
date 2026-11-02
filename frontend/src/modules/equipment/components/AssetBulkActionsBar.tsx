import { useTranslation } from "react-i18next";
import {
  Archive,
  MapPin,
  PackageCheck,
  PowerOff,
  QrCode,
  RefreshCw,
  Trash2,
  UserPlus,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { SelectionToolbar } from "@/module-sdk";
import { SendToPrinterButton } from "@/modules/shared/components/SendToPrinterButton";
import type { PrintTarget } from "@/modules/shared/lib/printQueue";

interface AssetBulkActionsBarProps {
  selectedCount: number;
  /**
   * How many records match the current filters and sit on another
   * page, out of reach of a tick. Rows on this page that are merely not
   * ticked do not count: they are one tap away. Zero when the page holds
   * everything the filters match.
   */
  unreachedMatches: number;
  /** Everything the current filters match, for "Select all N". */
  matchingTotal: number;
  /** The selection is the whole filtered set, not one page of ticks. */
  allMatching: boolean;
  listTab: "active" | "archived";
  onSelectAllMatching: () => void;
  onBulkRetire: () => void;
  onBulkArchive: () => void;
  onBulkPrintLabels: () => void;
  /** The selected assets' label codes, for "Send to printer"; null when none has one. */
  printTarget?: PrintTarget | null;
  onBulkReturn: () => void;
  onBulkPurge: () => void;
  onBulkChangeStatus: () => void;
  onBulkChangeLocation: () => void;
  onBulkAssignTo: () => void;
  onClearSelection: () => void;
}

/**
 * The equipment list's bulk actions, in the shared floating bar.
 *
 * It was a Card in the page flow with its count, its scope sentence and eight
 * buttons on one unwrapped row: at 390px the sentence was squeezed to one word
 * per line and Retire, Archive and Print labels sat past the screen edge with
 * no way to reach them. The shared bar wraps its actions onto lines of their
 * own, so every one of them is on screen without a sideways swipe, and gives
 * the scope sentence a line of its own, as the other lists already do.
 */
export function AssetBulkActionsBar({
  selectedCount,
  unreachedMatches,
  matchingTotal,
  allMatching,
  listTab,
  onSelectAllMatching,
  onBulkRetire,
  onBulkArchive,
  onBulkPrintLabels,
  printTarget = null,
  onBulkReturn,
  onBulkPurge,
  onBulkChangeStatus,
  onBulkChangeLocation,
  onBulkAssignTo,
  onClearSelection,
}: AssetBulkActionsBarProps) {
  const { t } = useTranslation("equipment");

  if (listTab === "archived") {
    return (
      <SelectionToolbar count={selectedCount} onClear={onClearSelection}>
        <Button
          variant="ghostDanger"
          size="sm"
          onClick={onBulkPurge}
          leftIcon={<Trash2 size={14} />}
        >
          {t("actions.bulk_purge")}
        </Button>
      </SelectionToolbar>
    );
  }

  // "50 selected" beside a header reading "61 assets" invited the reader to
  // take the two for the same set. The eleven that are not on this page are
  // out of reach of every button in this bar, so the bar is where that has to
  // be said -- before the click, not in the count afterwards.
  const note =
    unreachedMatches > 0 ? (
      <>
        {t("list.selection_page_only", { count: unreachedMatches })}{" "}
        {/* The server can run retire and archive over the filter itself,
            so the out-of-reach rows are one click away. */}
        <Button
          variant="ghost"
          size="inline"
          onClick={onSelectAllMatching}
          className="text-xs font-medium underline underline-offset-2"
        >
          {t("actions.select_all_matching", {
            total: matchingTotal,
          })}
        </Button>
      </>
    ) : allMatching ? (
      t("list.selection_all_matching", { count: selectedCount })
    ) : null;

  return (
    <SelectionToolbar
      count={selectedCount}
      onClear={onClearSelection}
      width="wide"
      note={note}
    >
      {/* Status, location, assignment, return and labels act on ids the
          reader ticked; over the whole set only retire and archive exist
          server-side, so the bar shows only what will work. */}
      {!allMatching && (
        <>
          <Button
            variant="outline"
            size="sm"
            onClick={onBulkChangeStatus}
            leftIcon={<RefreshCw size={14} />}
          >
            {t("bulk_edit.change_status", "Status")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={onBulkChangeLocation}
            leftIcon={<MapPin size={14} />}
          >
            {t("bulk_edit.change_location", "Location")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={onBulkAssignTo}
            leftIcon={<UserPlus size={14} />}
          >
            {t("bulk_edit.assign_to", "Assign")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={onBulkReturn}
            leftIcon={<PackageCheck size={14} />}
          >
            {t("actions.bulk_return", "Return Selected")}
          </Button>
        </>
      )}
      <Button
        variant="outline"
        size="sm"
        onClick={onBulkRetire}
        leftIcon={<PowerOff size={14} />}
      >
        {t("actions.bulk_retire")}
      </Button>
      <Button
        variant="outline"
        size="sm"
        onClick={onBulkArchive}
        leftIcon={<Archive size={14} />}
      >
        {t("actions.bulk_archive", "Archive")}
      </Button>
      {!allMatching && (
        <Button
          variant="outline"
          size="sm"
          onClick={onBulkPrintLabels}
          leftIcon={<QrCode size={14} />}
        >
          {t("actions.bulk_print_labels")}
        </Button>
      )}
      {!allMatching && (
        <SendToPrinterButton
          target={printTarget}
          size="sm"
          onSent={onClearSelection}
        />
      )}
    </SelectionToolbar>
  );
}
