import { useEffect, useRef, useState } from "react";
import { labelsApi } from "@/lib/api/labels";
import { extractApiError } from "@/lib/errors";

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
  /** The reader's names for the fields a refusal can name, by API key. */
  fieldNames?: Record<string, string>;
}

interface SheetPreview {
  /** Object URL of the rendered sheet, or null while there is nothing to show. */
  url: string | null;
  isLoading: boolean;
  failed: boolean;
  /** The server's own sentence when it refused the request, naming the field. */
  refusal: string | null;
}

/**
 * The preview of a label sheet — which is the sheet.
 *
 * The preview asks the generator for the actual PNG, the same call the download
 * makes, so there is one composition of the label and the preview shows what
 * the printer receives. It runs with `markPrinted` off, because looking at the
 * pool must not spend a label.
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
  fieldNames,
}: PreviewRequest): SheetPreview {
  const [url, setUrl] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const fieldNamesRef = useRef(fieldNames);
  useEffect(() => {
    fieldNamesRef.current = fieldNames;
  }, [fieldNames]);
  const currentUrl = useRef<string | null>(null);
  const ids = labelIds.join(",");

  useEffect(() => {
    if (!enabled || ids === "" || width <= 0 || height <= 0) return;

    let cancelled = false;
    setIsLoading(true);
    setFailed(false);
    setRefusal(null);

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
        .catch((error: unknown) => {
          if (cancelled) return;
          setFailed(true);
          // A 5xx reads as the empty string, which the window words itself.
          setRefusal(extractApiError(error, "", fieldNamesRef.current) || null);
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

  return { url, isLoading, failed, refusal };
}
