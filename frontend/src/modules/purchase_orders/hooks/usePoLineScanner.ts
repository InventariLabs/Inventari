import { extractApiError } from "@/lib/errors";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { useScanCamera } from "@/hooks/useScanCamera";
import { useScanResolver } from "@/hooks/useScanResolver";
import { scanSubjectKind } from "@/lib/scan/scanSubject";
import { lookupProductByBarcode } from "@/modules/shared/lib/productLookup";
import type { POLineInput } from "../components/POLinesSection";

interface UsePoLineScannerOptions {
  onAddOrIncrementLine: (
    updater: (lines: POLineInput[]) => POLineInput[],
  ) => void;
}

/**
 * Scanning products onto an order.
 *
 * Recognition is the registry's — the same chain every scanning screen uses.
 * What is specific to an order is what happens next: a line needs a product
 * template, so a recognized product goes through the barcode lookup that
 * yields one. A location or a document scanned here is a mistake worth
 * naming, and the resolver names it.
 */
export function usePoLineScanner({
  onAddOrIncrementLine,
}: UsePoLineScannerOptions) {
  const { t } = useTranslation(["purchase_orders", "common"]);
  const [scanOpen, setScanOpen] = useState(false);
  const [scanLoading, setScanLoading] = useState(false);

  const addScannedProduct = useCallback(
    async (code: string) => {
      setScanLoading(true);
      try {
        const lookupResult = await lookupProductByBarcode(code).catch(
          () => null,
        );
        if (!lookupResult) {
          toast(t("form.scanUnknown"));
          return;
        }
        onAddOrIncrementLine((prev) => {
          const existing = prev.find(
            (l) => l.product_template_id === lookupResult.product_template_id,
          );
          if (existing) {
            return prev.map((l) =>
              l.id === existing.id
                ? { ...l, quantity_ordered: l.quantity_ordered + 1 }
                : l,
            );
          }
          return [
            ...prev,
            {
              id: `scan-${Date.now()}`,
              product_template_id: lookupResult.product_template_id ?? null,
              name: lookupResult.name,
              sku: lookupResult.sku ?? null,
              barcode: code,
              brand: lookupResult.brand ?? null,
              image_url: lookupResult.image_url ?? null,
              quantity_ordered: 1,
              unit_price: "",
              tax_rate: "",
              uom_id: lookupResult.uom_id ?? null,
            },
          ];
        });
        toast.success(
          t("purchase_orders:form.addedOne", { name: lookupResult.name }),
        );
      } catch (error) {
        toast.error(extractApiError(error, t("form.scanError")));
      } finally {
        setScanLoading(false);
      }
    },
    [onAddOrIncrementLine, t],
  );

  const { resolve } = useScanResolver({
    handle: async (result, code) => {
      const kind = scanSubjectKind(result);
      if (kind === "storage" || kind === "document") return false;
      await addScannedProduct(code);
      return true;
    },
    acceptUnrecognized: () => {
      toast(t("form.scanUnknown"));
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
    setIsCameraActive,
  } = useScanCamera({ onCodeScanned: handleCodeScanned });

  // The camera effect looks for #qr-reader when it starts, and the panel that
  // holds it is closed until the user opens it — so opening has to start the
  // camera afresh, and closing has to switch it off (it releases the track).
  const toggleScan = useCallback(() => {
    if (scanOpen) {
      setScanOpen(false);
      setIsCameraActive(false);
    } else {
      setScanOpen(true);
      restartCamera();
    }
  }, [scanOpen, restartCamera, setIsCameraActive]);

  return {
    handleCodeScanned,
    scanOpen,
    toggleScan,
    scanLoading,
    isCameraActive,
    scannerError,
    isTorchOn,
    toggleTorch,
  };
}
