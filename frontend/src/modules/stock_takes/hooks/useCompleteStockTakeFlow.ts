import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useConfirm } from "@/hooks/useConfirm";
import { useHasPermission } from "@/hooks/useHasPermission";
import { useCompleteStockTake } from "@/modules/stock_takes/hooks/useStockTakes";
import type { StockTakeItem } from "@/modules/stock_takes/types/stock-takes";
import { extractApiError, extractApiErrorRows } from "@/lib/errors";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";

/** How many offending rows the confirmation names before it summarizes. */
const ROWS_SHOWN = 3;

/** Which refusals the reader has already answered for, on this attempt. */
interface ForceFlags {
  forceOverCap: boolean;
  forceOverTolerance: boolean;
}

/**
 * Finishing a stock take, including the case the server refuses.
 *
 * A counted quantity far above the system stock is held back rather than
 * trimmed: the server answers 409 and names the rows, and the person who
 * counted says whether the number is real. Lives apart from
 * `useStockTakeCounting` because two confirmations and a retry are a flow of
 * their own, not another branch of the counting screen's state.
 */
export function useCompleteStockTakeFlow(
  id: string | undefined,
  lines: StockTakeItem[] | undefined,
  confirm: ReturnType<typeof useConfirm>["confirm"],
  unsavedCount = 0,
  requireFullCount = false,
) {
  const { t } = useTranslation(["stock_takes"]);
  const navigate = useNavigate();
  const completeMutation = useCompleteStockTake(id);
  const completeMutate = completeMutation.mutate;
  // Accepting a difference the organization's own tolerance calls too large
  // — or a count far above the system stock — is not the counter's decision.
  // One key, `stock_takes:approve`, guards both refusals on the server. Asked
  // here as well as enforced there, so somebody who cannot accept it is told
  // that instead of being offered a button that answers 403.
  const mayAcceptOverrides = useHasPermission("stock_takes:approve");

  const handleComplete = useCallback(async () => {
    // A unit counted away from where its record stands is moved there even
    // when the number agrees — the same rows the server's report counts.
    // The sentences name products, and one product can stand as several
    // records (two receipts into one place): those are one product to the
    // reader, told by the name and brand every row of the count shows.
    const productsIn = (rows: StockTakeItem[]) =>
      new Set(
        rows.map((line) => `${line.item_name}\u0000${line.item_brand ?? ""}`),
      ).size;
    const adjustments = productsIn(
      (lines ?? []).filter(
        (line) =>
          line.counted_quantity != null &&
          (line.counted_quantity !== line.system_quantity ||
            line.expected_location_id != null),
      ),
    );

    // The numbers typed but not saved, in the words the confirmation uses.
    const unsavedSentence =
      unsavedCount > 0
        ? t("confirm.complete.unsaved", { count: unsavedCount })
        : "";

    // A stock take that requires a full count refuses to close over any line
    // without a number. Said before the confirmation, because that dialog
    // offers Complete and a refusal after it takes the offer back. A number
    // still in its box is not a count yet, so the refusal carries the unsaved
    // sentence too: what is missing may be a Save, not a count.
    const uncounted = productsIn(
      (lines ?? []).filter((line) => line.counted_quantity == null),
    );
    if (requireFullCount && uncounted > 0) {
      toast.error(
        [t("errors.uncountedRemaining", { count: uncounted }), unsavedSentence]
          .filter(Boolean)
          .join(" "),
      );
      return;
    }

    const goToReport = () => navigate(`/inventory/stock-takes/${id}/report`);
    const reportFailure = (error: Error) =>
      toast.error(extractApiError(error, t("errors.completeFailed")));

    // Numbers still sitting in their input boxes are not part of the count
    // and completing throws them away. Said here because this is the last
    // moment anyone can go back for them — and because a stock take with
    // "require full count" set refuses to close over exactly those rows,
    // with nothing on the screen explaining which ones.
    const message = [
      t("confirm.complete.message", { count: adjustments }),
      unsavedSentence,
    ]
      .filter(Boolean)
      .join(" ");

    const proceed = await confirm({
      title: t("confirm.complete.title"),
      message,
      variant: "danger",
      confirmLabel: t("confirm.complete.confirmLabel"),
    });
    if (!proceed) return;

    // The card behind this dialog names the unit beside every quantity, and
    // this is the screen where somebody accepts a loss on stock: "counted
    // 2.15, system 7.8" says nothing about whether that is kilograms or
    // boxes. The rows come off the wire with the item id, so the symbol is
    // read from the lines already on screen rather than asked of the server.
    const lineOf = (itemId: unknown) =>
      (lines ?? []).find((line) => line.item_id === itemId);
    // The same formatter the card behind this dialog uses, with the unit's
    // own rounding: "2,15 kg" here and there. A decimal trimmer wrote the
    // database's point, so the card said 2,15 and this said 2.15.
    const figure = (value: unknown, itemId: unknown) => {
      const line = lineOf(itemId);
      return formatQuantityLocalized(
        t,
        Number(value ?? 0),
        line?.uom_symbol?.trim() || null,
        line?.uom_rounding,
      );
    };
    // The rows end where the message's own sentence does. A unit written as
    // an abbreviation ends in a full stop ("pcs.", "szt."), and the message
    // adds one after the rows — "2 pcs.." — so the last row gives its dot up.
    // Presentation only: the unit dictionary the cards read stays as it is.
    const namedRows = (rows: Record<string, unknown>[]) =>
      rows
        .slice(0, ROWS_SHOWN)
        .map((row) =>
          t("confirm.overCap.row", {
            name: String(row.item_name ?? ""),
            counted: figure(row.counted_quantity, row.item_id),
            system: figure(row.system_quantity, row.item_id),
          }),
        )
        .join("; ")
        .replace(/\.$/, "");

    const askAboutOverCap = async (rows: Record<string, unknown>[]) =>
      confirm({
        title: t("confirm.overCap.title"),
        message: t("confirm.overCap.message", {
          count: rows.length,
          rows: namedRows(rows),
        }),
        variant: "danger",
        confirmLabel: t("confirm.overCap.confirmLabel"),
      });

    const askAboutOverTolerance = async (rows: Record<string, unknown>[]) =>
      confirm({
        title: t("confirm.overTolerance.title"),
        message: t("confirm.overTolerance.message", {
          count: rows.length,
          rows: namedRows(rows),
        }),
        variant: "danger",
        confirmLabel: t("confirm.overTolerance.confirmLabel"),
      });

    // The server answers one refusal at a time, and so does this: a
    // difference nobody has explained cannot be accepted, so that message
    // stands on its own and no button offers to override it.
    const handleRefusal = async (error: Error, force: ForceFlags) => {
      const unexplained = extractApiErrorRows(error, "unexplained_items");
      if (unexplained && unexplained.length > 0) {
        // Said here rather than repeated off the wire: the server's answer is
        // written for whatever reads the API and counts in brackets, and this
        // is the screen where somebody is being asked to go back and type a
        // reason on each of those rows.
        toast.error(
          t("errors.unexplainedDifferences", { count: unexplained.length }),
        );
        return;
      }
      const overTolerance = extractApiErrorRows(error, "over_tolerance_items");
      if (overTolerance && overTolerance.length > 0) {
        if (!mayAcceptOverrides) {
          toast.error(t("errors.overToleranceNotAllowed"));
          return;
        }
        if (await askAboutOverTolerance(overTolerance)) {
          retry({ ...force, forceOverTolerance: true });
        }
        return;
      }
      const overCap = extractApiErrorRows(error, "over_cap_items");
      if (overCap && overCap.length > 0) {
        if (!mayAcceptOverrides) {
          toast.error(t("errors.overCapNotAllowed"));
          return;
        }
        if (await askAboutOverCap(overCap)) {
          retry({ ...force, forceOverCap: true });
        }
        return;
      }
      reportFailure(error);
    };

    const retry = (force: ForceFlags) =>
      completeMutate(force, {
        onSuccess: goToReport,
        onError: (error: Error) => void handleRefusal(error, force),
      });

    retry({ forceOverCap: false, forceOverTolerance: false });
  }, [
    confirm,
    completeMutate,
    navigate,
    id,
    t,
    lines,
    unsavedCount,
    requireFullCount,
    mayAcceptOverrides,
  ]);

  return { handleComplete, completeMutation };
}
