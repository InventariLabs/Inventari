import { extractApiError } from "@/lib/errors";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { toast } from "sonner";
import { useScanCamera } from "@/hooks/useScanCamera";
import { useScanResolver } from "@/hooks/useScanResolver";
import { storagesApi } from "@/lib/api/storages";
import { scanSubjectKind } from "@/lib/scan/scanSubject";
import { lookupProductByBarcode } from "@/modules/shared/lib/productLookup";
import { itemSku, productCode, type Item, type LabelScanView } from "@/types";
import type {
  ReceiptDraftLine,
  QuickAddLineDraft,
} from "../components/documentFormShared";

interface UseDocumentScannerOptions {
  onAddOrIncrementLine: (line: ReceiptDraftLine) => void;
  onOpenQuickAdd: (prefill?: Partial<QuickAddLineDraft>) => void;
  /**
   * Where the document's lines take their stock record from. `locationId` is
   * set when the lines name a record, so a scan has to pick one: the shelf it
   * takes goods from, or null while none is chosen. When the source is a
   * zone, a dispatch takes from the shelves under it, so a record standing on
   * one of them is in the source too — asked of the server for the shelves
   * the scanned product stands on, not read from a list of the zone.
   */
  stock?: {
    locationId?: string | null;
  };
  /**
   * Say "added" once the scan became a line. Off where a scan only proposes
   * the line and the person confirms the count first (the phone's one by one).
   */
  announceAdded?: boolean;
  /**
   * A location's label scanned into the line list. Where the screen asks for
   * a place (an issue's source, a move's two ends) the same scan answers it;
   * elsewhere a location is not a line and the scan is left unhandled.
   */
  onLocationScanned?: (locationId: string, name: string) => void;
}

type ScannedRecord = NonNullable<
  LabelScanView["stock_summary"]
>["items"][number];

/** Earliest first; a record with nothing to compare goes last. */
function byRemovalOrder(strategy: "FIFO" | "FEFO" | undefined) {
  const age = (r: ScannedRecord) => r.created_at ?? "";
  return (a: ScannedRecord, b: ScannedRecord) => {
    if (strategy === "FEFO") {
      const byExpiry = (a.expiry_date ?? "9999").localeCompare(
        b.expiry_date ?? "9999",
      );
      if (byExpiry !== 0) return byExpiry;
    }
    return age(a).localeCompare(age(b));
  };
}

/** A line for a stock record named by its label: the product's own code. */
function lineFromItem(item: Item): ReceiptDraftLine {
  return {
    _key: crypto.randomUUID(),
    item_id: item.id,
    name: item.name,
    brand: item.brand ?? undefined,
    barcode: productCode(item) ?? "",
    sku: itemSku(item) ?? undefined,
    image_url: item.image_url ?? undefined,
    quantity: 1,
    uom_id: item.uom_id ?? null,
    batch_number: "",
    expiry_date: "",
    notes: "",
    unit_price: "",
    tax_rate: "",
  };
}

/**
 * The record a scan lands on. A line that takes goods off a shelf names one
 * record, and the person is standing at the source shelf: the non-empty
 * records there, in the order the product leaves in — not the newest record
 * anywhere, empty ones included. With none, `places` names where the stock
 * stands instead (empty when it stands nowhere). While no shelf is chosen
 * there is no record to name. A zone's source counts the shelves below it.
 */
function recordForLine(
  summary: LabelScanView["stock_summary"],
  stockLocationId: string | null | undefined,
  shelvesBelowSource: ReadonlySet<string> | undefined,
) {
  const items = summary?.items ?? [];
  if (stockLocationId === undefined) return { record: items[0], places: "" };
  const stocked = items
    .filter((r) => r.quantity > 0)
    .sort(byRemovalOrder(summary?.removal_strategy));
  // One entry per place: a shelf holding three records is one place.
  const perPlace = new Map<string, { name: string; quantity: number }>();
  for (const r of stocked) {
    const place = perPlace.get(r.location_id ?? r.location);
    if (place) place.quantity += r.quantity;
    else
      perPlace.set(r.location_id ?? r.location, {
        name: r.location,
        quantity: r.quantity,
      });
  }
  return {
    record: stockLocationId
      ? stocked.find(
          (r) =>
            r.location_id === stockLocationId ||
            (!!r.location_id && !!shelvesBelowSource?.has(r.location_id)),
        )
      : undefined,
    places: [...perPlace.values()]
      .map((p) => `${p.name} (${p.quantity})`)
      .join(", "),
  };
}

/**
 * Which of the places a scanned product stands on lie inside the source.
 *
 * Asked of the server for just those places: a zone's shelves are not
 * downloaded to answer it. A source that is itself a shelf has nothing below
 * it, so nothing is asked.
 */
async function placesInsideSource(
  summary: LabelScanView["stock_summary"],
  sourceId: string | null | undefined,
): Promise<ReadonlySet<string> | undefined> {
  if (!sourceId) return undefined;
  const standing = [
    ...new Set(
      (summary?.items ?? [])
        .filter((r) => r.quantity > 0 && r.location_id)
        .map((r) => r.location_id as string)
        .filter((id) => id !== sourceId),
    ),
  ];
  if (standing.length === 0) return undefined;
  const found = await storagesApi.getPage({
    under: sourceId,
    ids: standing,
    usage: "all",
    include_archived: true,
    counts: false,
    limit: 200,
  });
  return new Set(found.items.map((place) => place.id));
}

/** Why a scan into a dispatch found no record to name. */
function noRecordMessage(
  t: TFunction,
  name: string,
  stockLocationId: string | null | undefined,
  places: string,
) {
  if (stockLocationId === null) return t("warehouse:scan.chooseSource");
  if (!places) return t("warehouse:scan.notAnywhere", { name });
  return t("warehouse:scan.notInSource", { name, places });
}

export function useDocumentScanner({
  onAddOrIncrementLine,
  onOpenQuickAdd,
  stock,
  announceAdded = true,
  onLocationScanned,
}: UseDocumentScannerOptions) {
  const { t } = useTranslation("warehouse");
  const stockLocationId = stock?.locationId;
  const [scanOpen, setScanOpen] = useState(false);
  const [scanLoading, setScanLoading] = useState(false);

  // "Added" once a scan became a line — not where it only proposes one.
  const announce = useCallback(
    (name: string) => {
      if (announceAdded) {
        toast.success(t("warehouse:lines.addedOne", { name }));
      }
    },
    [announceAdded, t],
  );

  // Recognition is shared; what a document line does with the result
  // is not. A location or a document number scanned into the line list is a
  // mistake worth naming rather than an "unknown code".
  const addScannedProduct = useCallback(
    async (result: LabelScanView, code: string) => {
      setScanLoading(true);

      try {
        const template = result.stock_summary?.template;
        const stockItems = result.stock_summary?.items;

        if (result.action === "show_stock_actions" && stockItems?.length) {
          const productName = template?.name ?? code;

          const { record, places } = recordForLine(
            result.stock_summary,
            stockLocationId,
            await placesInsideSource(result.stock_summary, stockLocationId),
          );
          if (!record) {
            toast.warning(
              noRecordMessage(t, productName, stockLocationId, places),
            );
            return;
          }

          onAddOrIncrementLine({
            _key: crypto.randomUUID(),
            item_id: record.id,
            name: productName,
            brand: template?.brand ?? undefined,
            barcode: code,
            sku: template?.sku ?? undefined,
            image_url: template?.image_url ?? undefined,
            quantity: 1,
            uom_id: template?.uom_id,
            batch_number: "",
            expiry_date: "",
            notes: "",
            unit_price: "",
            tax_rate: "",
          });
          announce(productName);
          return;
        }

        if (
          result.action === "show_quick_add" ||
          result.action === "show_stock_actions"
        ) {
          if (!template) {
            const lookupResult = await lookupProductByBarcode(code);
            if (lookupResult) {
              onOpenQuickAdd({
                name: lookupResult.name,
                brand: lookupResult.brand ?? "",
                barcode: code,
                image_url: lookupResult.image_url ?? undefined,
                uom_id: lookupResult.uom_id ?? null,
                product_template_id: lookupResult.product_template_id,
              });
              return;
            }
            onOpenQuickAdd({
              name: "",
              brand: "",
              barcode: code,
              image_url: undefined,
              uom_id: null,
            });
          } else {
            onOpenQuickAdd({
              name: template?.name ?? "",
              brand: template?.brand ?? "",
              barcode: code,
              image_url: template?.image_url ?? undefined,
              uom_id: template?.uom_id ?? null,
              product_template_id: template.id,
            });
          }
          return;
        }

        toast(t("scan.unknownCode"));
      } catch (error) {
        toast.error(extractApiError(error, t("scan.error")));
      } finally {
        setScanLoading(false);
      }
    },
    [onAddOrIncrementLine, onOpenQuickAdd, stockLocationId, announce, t],
  );

  // A location's label answers the screen's question about a place, where it
  // asks one; elsewhere it is left unhandled.
  const takeLocation = (result: LabelScanView): boolean => {
    if (!onLocationScanned || !result.location) return false;
    onLocationScanned(result.location.id, result.location.name);
    return true;
  };

  const { resolve } = useScanResolver({
    handle: async (result, code) => {
      const kind = scanSubjectKind(result);
      if (kind === "storage") return takeLocation(result);
      if (kind === "document") return false;
      // A printed label names a stock record directly; its code is the
      // product's own, not the address the QR happened to carry.
      if (result.action === "show_quick_actions" && result.item) {
        onAddOrIncrementLine(lineFromItem(result.item));
        announce(result.item.name);
        return true;
      }
      await addScannedProduct(result, code);
      return true;
    },
    acceptUnrecognized: () => {
      toast(t("scan.unknownCode"));
      return true;
    },
  });

  const handleCodeScanned = useCallback(
    (code: string) => void resolve(code),
    [resolve],
  );

  const {
    isCameraActive,
    scannerError,
    isTorchOn,
    toggleTorch,
    restartCamera,
  } = useScanCamera({
    onCodeScanned: handleCodeScanned,
  });

  return {
    handleCodeScanned,
    scanOpen,
    setScanOpen,
    scanLoading,
    isCameraActive,
    scannerError,
    isTorchOn,
    toggleTorch,
    restartCamera,
  };
}
