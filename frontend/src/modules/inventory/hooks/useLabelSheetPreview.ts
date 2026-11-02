import { useEffect, useRef, useState } from "react";
import { labelsApi } from "@/lib/api/labels";

interface PreviewRequest {
  labelIds: string[];
  width: number;
  height: number;
  publicUrl: string;
  description: string;
  qrOnly: boolean;
  copiesPerLabel: number;
  showCode: boolean;
  enabled: boolean;
}

interface SheetPreview {
  /** Object URL of the rendered sheet, or null while there is nothing to show. */
  url: string | null;
  isLoading: boolean;
  failed: boolean;
}

/**
 * The preview of a label sheet — which is the sheet.
 *
 * The window used to draw its own composition in HTML: a box in the label's
 * proportions, a QR at 90% of its height, the code at a sixth of it. The
 * generator drew another one, on a canvas three quarters as tall, with the
 * code at 38%. Two independent compositions of the same label, and the file
 * was the one nobody had seen until it came out of the printer. So the
 * preview asks the generator for the actual PNG — the same call the download
 * makes, with `markPrinted` off, because looking at the pool must not spend
 * it.
 *
 * Debounced: the description field changes the settings on every keystroke,
 * and every change is a render on the server.
 */
export function useLabelSheetPreview({
  labelIds,
  width,
  height,
  publicUrl,
  description,
  qrOnly,
  copiesPerLabel,
  showCode,
  enabled,
}: PreviewRequest): SheetPreview {
  const [url, setUrl] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const currentUrl = useRef<string | null>(null);
  const ids = labelIds.join(",");

  useEffect(() => {
    if (!enabled || ids === "" || width <= 0 || height <= 0) return;

    let cancelled = false;
    setIsLoading(true);
    setFailed(false);

    const timer = setTimeout(() => {
      const expanded = ids
        .split(",")
        .flatMap((id) => Array(Math.max(1, copiesPerLabel)).fill(id));
      labelsApi
        .exportPng({
          count: expanded.length,
          labelIds: expanded,
          width,
          height,
          baseUrl: publicUrl,
          description: description || undefined,
          qrOnly: qrOnly || undefined,
          showCode,
          markPrinted: false,
        })
        .then((blob) => {
          if (cancelled) return;
          // The previous sheet stays on screen until this one is ready, so
          // the panel does not blink white between keystrokes.
          const previous = currentUrl.current;
          currentUrl.current = URL.createObjectURL(blob);
          setUrl(currentUrl.current);
          if (previous) URL.revokeObjectURL(previous);
        })
        .catch(() => {
          if (!cancelled) setFailed(true);
        })
        .finally(() => {
          if (!cancelled) setIsLoading(false);
        });
    }, 400);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [
    enabled,
    ids,
    width,
    height,
    publicUrl,
    description,
    qrOnly,
    copiesPerLabel,
    showCode,
  ]);

  useEffect(
    () => () => {
      if (currentUrl.current) URL.revokeObjectURL(currentUrl.current);
    },
    [],
  );

  return { url, isLoading, failed };
}
