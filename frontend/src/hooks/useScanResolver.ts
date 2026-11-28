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
  /**
   * Set where each read is one piece: the code still waiting, read again, is
   * then answered too. The camera reports a code it holds in view once, so its
   * second report is a second showing.
   */
  everyReadCounts?: boolean;
}

/**
 * One recognition chain for every scanning screen.
 *
 * Recognition is shared; what a screen does with the result is not. A screen
 * that cannot act on what was scanned says what it is and offers to hand the
 * reader on with the code intact — the code is never rejected as
 * "not found" when the system knows perfectly well what it is.
 *
 * A scanner does not wait for the screen: codes are looked up one at a time,
 * in the order they were read, and each one is answered.
 */
export function useScanResolver({
  handle,
  acceptUnrecognized,
  everyReadCounts = false,
}: UseScanResolverOptions) {
  const { t } = useTranslation("scan");
  const navigate = useNavigate();
  const [isResolving, setIsResolving] = useState(false);
  // The codes not answered yet, the one being looked up first.
  const pending = useRef<string[]>([]);
  const lastTurn = useRef(Promise.resolve());
  const unmounted = useRef(false);
  // The screen's answers are taken when the lookup comes back, so a code
  // that waited is judged against what the one before it changed.
  const screen = useRef({ handle, acceptUnrecognized });
  screen.current = { handle, acceptUnrecognized };
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

  useEffect(() => {
    unmounted.current = false;
    return () => {
      unmounted.current = true;
    };
  }, []);

  const lookup = useCallback(
    async (rawCode: string, code: string, abandoned: () => boolean) => {
      try {
        const result = await labelsApi.scan(code);
        if (abandoned()) return;
        if (await screen.current.handle(result, code)) return;
        announceElsewhere(scanSubject(result, code));
      } catch (error) {
        if (
          extractApiErrorCode(error) === "SCAN_UNRECOGNIZED" &&
          screen.current.acceptUnrecognized?.(code)
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
      }
    },
    [announceElsewhere, navigate, t],
  );

  const resolve = useCallback(
    (rawCode: string): Promise<void> => {
      // A camera or a field may hand over a QR's whole address.
      const code = scannedCode(rawCode);
      // Where a scan looks something up, the code just read, still
      // unanswered, is the same reading: a nervous thumb or a symbol shown
      // again asks nothing new.
      const repeated = !everyReadCounts && pending.current.at(-1) === code;
      if (!code || repeated) return Promise.resolve();
      // A screen that is gone asks nothing more of what was still waiting:
      // the first answer may be what took the reader elsewhere.
      const waited = pending.current.length > 0;
      const abandoned = () => waited && unmounted.current;
      pending.current.push(code);
      setIsResolving(true);
      const run = async () => {
        try {
          if (!abandoned()) await lookup(rawCode, code, abandoned);
        } finally {
          pending.current.shift();
          if (pending.current.length === 0) setIsResolving(false);
        }
      };
      // With nothing ahead of it a code is asked for at once.
      lastTurn.current = waited ? lastTurn.current.then(run, run) : run();
      return lastTurn.current;
    },
    [everyReadCounts, lookup],
  );

  useEffect(() => {
    resolveRef.current = resolve;
  }, [resolve]);

  return { resolve, isResolving };
}
