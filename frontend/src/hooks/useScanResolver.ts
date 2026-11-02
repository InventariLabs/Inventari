import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { labelsApi } from "@/lib/api/labels";
import { extractApiErrorCode } from "@/lib/errors";
import { scannedCode } from "@/lib/scan/scannedCode";
import { scanLookupError } from "@/lib/scan/toastScanError";
import {
  scanSubject,
  searchActionFor,
  type ScanSubject,
  type ScanSubjectKind,
} from "@/lib/scan/scanSubject";
import type { LabelScanView } from "@/types";

/** Static keys, so the i18n gate can see them — a template literal is
 *  invisible to it, and an orphaned key is indistinguishable from a dead one. */
const ELSEWHERE_KEY: Record<ScanSubjectKind, string> = {
  product: "elsewhere.product",
  blankLabel: "elsewhere.blankLabel",
  archived: "elsewhere.archived",
  storage: "elsewhere.storage",
  document: "elsewhere.document",
};

interface UseScanResolverOptions {
  /**
   * What this screen does with a recognized code. Return `true` when the
   * screen handled it (including when it said so itself), `false` to hand the
   * reader the "this is a X, open it there?" offer instead.
   */
  handle: (result: LabelScanView, code: string) => boolean | Promise<boolean>;
  /**
   * What this screen does with a code no provider recognized. A form that
   * records a manufacturer barcode legitimately accepts one; a screen that
   * looks records up does not, and gets the backend's SCAN_UNRECOGNIZED
   * message instead.
   */
  acceptUnrecognized?: (code: string) => boolean;
}

/**
 * One recognition chain for every scanning screen.
 *
 * Recognition is shared; what a screen does with the result is not. A screen
 * that cannot act on what was scanned says what it is and offers to hand the
 * reader on with the code intact — the code is never rejected as
 * "not found" when the system knows perfectly well what it is.
 */
export function useScanResolver({
  handle,
  acceptUnrecognized,
}: UseScanResolverOptions) {
  const { t } = useTranslation("scan");
  const navigate = useNavigate();
  const [isResolving, setIsResolving] = useState(false);
  // The camera fires repeatedly at the same symbol; a lookup in flight must
  // not queue up behind itself.
  const inFlight = useRef(false);
  // A failed lookup offers to run the same code again, and the toast with
  // that offer outlives the render that raised it — the attempt goes
  // through whichever `resolve` is current when the button is pressed.
  const resolveRef = useRef<(rawCode: string) => Promise<void>>(async () => {});

  const announceElsewhere = useCallback(
    (subject: ScanSubject) => {
      toast(t(ELSEWHERE_KEY[subject.kind], { name: subject.name }), {
        description: t("elsewhere.description"),
        action: {
          label: t("elsewhere.action"),
          onClick: () => navigate(subject.target),
        },
      });
    },
    [navigate, t],
  );

  const resolve = useCallback(
    async (rawCode: string) => {
      // A camera or a field may hand over a QR's whole address.
      const code = scannedCode(rawCode);
      if (!code || inFlight.current) return;
      inFlight.current = true;
      setIsResolving(true);
      try {
        const result = await labelsApi.scan(code);
        if (await handle(result, code)) return;
        announceElsewhere(scanSubject(result, code));
      } catch (error) {
        if (
          extractApiErrorCode(error) === "SCAN_UNRECOGNIZED" &&
          acceptUnrecognized?.(code)
        ) {
          return;
        }
        // Nothing matched the code. Trying it again cannot change that; the
        // search can, because it looks wherever a record keeps a code.
        const search = searchActionFor(
          error,
          code,
          t("searchForCode"),
          navigate,
        );
        if (search) {
          toast.error(scanLookupError(error, t("errorScanning"), t), {
            action: search,
          });
          return;
        }
        // Not "scanning error" — nothing about scanning broke. The lookup
        // is what went unanswered, and the sentence says so and hands the
        // same code back: one press asks again, instead of the reader
        // retyping a code they typed correctly the first time.
        const failed = toast.error(
          scanLookupError(error, t("errorScanning"), t),
          {
            action: {
              label: t("retry"),
              onClick: () => {
                // The refusal has been answered — a second attempt must not
                // leave the first one's sentence on screen beside it.
                toast.dismiss(failed);
                void resolveRef.current(rawCode);
              },
            },
          },
        );
      } finally {
        inFlight.current = false;
        setIsResolving(false);
      }
    },
    [acceptUnrecognized, announceElsewhere, handle, navigate, t],
  );

  useEffect(() => {
    resolveRef.current = resolve;
  }, [resolve]);

  return { resolve, isResolving };
}
