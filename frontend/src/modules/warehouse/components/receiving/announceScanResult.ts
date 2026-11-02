import type { TFunction } from "i18next";
import { toast } from "sonner";
import { unitLabel } from "@/lib/i18nHelpers";
import type { WmsReceiveScanResult } from "@/modules/warehouse/api/documents_receiving";

/**
 * The sentence for a scan the delivery does not take: a product that is not on
 * it, or one whose line is already received. It names the product, which the
 * worker holding it up to a camera has no other way to check was the one read.
 */
export function receivingRefusal(
  t: TFunction,
  result: WmsReceiveScanResult | null | undefined,
): string | null {
  if (result?.status === "not_in_document") {
    return t("warehouse:receiving.toast.not_in_document", {
      product: result.product_name ?? "",
    });
  }
  if (result?.status === "already_received") {
    return t("warehouse:receiving.toast.already_received", {
      product: result.product_name ?? "",
      qty: result.received_quantity,
      expected: result.expected_quantity,
      uom: unitLabel(t, result.uom_symbol),
    });
  }
  if (result?.status === "rejected") {
    return t("warehouse:receiving.toast.document_closed");
  }
  return null;
}

/** What the server's answer to a receiving scan says to the worker. */
export function announceScanResult(
  t: TFunction,
  result: WmsReceiveScanResult | null,
  barcode: string,
) {
  if (!result) return;
  if (result.status === "received") {
    toast.success(
      t("warehouse:receiving.toast.received", {
        product: result.product_name ?? "",
        qty: result.received_quantity,
        uom: unitLabel(t, result.uom_symbol),
      }),
    );
  } else if (result.status === "shelf_confirmed") {
    toast.success(
      t("warehouse:receiving.toast.shelf_confirmed", {
        location: result.shelf,
      }),
    );
  } else if (result.status === "shelf_required") {
    toast.error(
      t("warehouse:receiving.toast.shelf_required", { location: result.shelf }),
    );
  } else if (result.status === "wrong_shelf") {
    toast.error(
      t("warehouse:receiving.toast.wrong_shelf", { location: result.shelf }),
    );
  } else if (result.status === "not_found") {
    // A code no product carries: name it, and the place a worker gives a
    // product its code — the terminal has no way to do that itself.
    toast.error(t("warehouse:receiving.toast.not_found", { code: barcode }), {
      description: t("warehouse:receiving.toast.not_found_hint"),
    });
  } else if (result.status === "not_in_document") {
    toast.error(receivingRefusal(t, result));
  } else if (
    result.status === "already_received" ||
    result.status === "rejected"
  ) {
    toast.error(receivingRefusal(t, result));
  } else if (result.status === "over_quantity") {
    // the server refuses over-receiving and said so; the screen used to
    // swallow the answer and look like nothing had happened.
    toast.error(
      t("warehouse:receiving.toast.over_quantity", {
        qty: result.received_quantity,
        expected: result.expected_quantity,
        uom: unitLabel(t, result.uom_symbol),
      }),
    );
  } else if (result.status === "all_received") {
    toast(t("warehouse:receiving.toast.all_received"));
  } else if (result.status === "lot_too_small") {
    toast.error(
      t("warehouse:receiving.toast.lot_too_small", {
        lot: result.lot_name ?? "",
      }),
    );
  } else if (
    result.status === "identified" ||
    result.status === "needs_lot_expiry" ||
    result.status === "needs_surplus_confirmation" ||
    result.status === "short_receive_confirmed" ||
    result.status === "short"
  ) {
    // The phone card or its questions handle these responses.
  } else {
    const unhandled: never = result.status;
    return unhandled;
  }
}
