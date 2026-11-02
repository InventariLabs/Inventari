import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api/client";
import { extractApiError } from "@/lib/errors";

/** Whose labels with bars: products', or shelves' — a location's code in
 *  Code 128 for a 1D scanner. */
export type BarcodeLabelTarget =
  { itemIds: string[] } | { storageIds: string[] };

export interface BarcodeLabelOptions {
  width: number;
  height: number;
  copies: number;
  /** A product label's lot and expiry line, when the record has them. */
  details: boolean;
  /** A shelf label's QR beside the bars, for a phone camera. */
  qr: boolean;
}

export interface BarcodeLabelFile {
  blob: Blob;
  /** Chosen products or locations left out because they carry no code. */
  withoutCode: number;
  /** Products among the printed ones that have a lot or an expiry date to
   *  print, or null when the server does not say (shelf labels). */
  withDetails: number | null;
}

function targetIds(target: BarcodeLabelTarget): string[] {
  return "itemIds" in target ? target.itemIds : target.storageIds;
}

/** The labels as one PNG — the preview and the download. */
export async function fetchBarcodeLabels(
  target: BarcodeLabelTarget,
  options: BarcodeLabelOptions,
): Promise<BarcodeLabelFile> {
  const size = {
    width_mm: options.width,
    height_mm: options.height,
    copies: options.copies,
  };
  const response =
    "itemIds" in target
      ? await api.post<Blob>(
          "/printing/product-labels/png",
          { item_ids: target.itemIds, details: options.details, ...size },
          { responseType: "blob" },
        )
      : await api.post<Blob>(
          "/printing/location-labels/png",
          { location_ids: target.storageIds, qr: options.qr, ...size },
          { responseType: "blob" },
        );
  const withDetails = response.headers["x-labels-with-details"];
  return {
    blob: response.data,
    withoutCode: Number(response.headers["x-labels-without-code"] ?? 0),
    withDetails: withDetails === undefined ? null : Number(withDetails),
  };
}

interface BarcodeLabelPreview {
  /** Object URL of the rendered sheet, or null while there is nothing to show. */
  url: string | null;
  withoutCode: number;
  withDetails: number | null;
  isLoading: boolean;
  /** The server's sentence when it refused, e.g. none of them has a code. */
  error: string | null;
}

/**
 * The preview of the labels, which is the file the download gives.
 *
 * Debounced like the pool's preview: the size fields change on every
 * keystroke, and each change is a render on the server.
 */
export function useBarcodeLabelPreview(
  target: BarcodeLabelTarget,
  options: BarcodeLabelOptions,
  failedText: string,
): BarcodeLabelPreview {
  const [state, setState] = useState<Omit<BarcodeLabelPreview, "url">>({
    withoutCode: 0,
    withDetails: null,
    isLoading: false,
    error: null,
  });
  const [url, setUrl] = useState<string | null>(null);
  const currentUrl = useRef<string | null>(null);
  const kind = "itemIds" in target ? "items" : "storages";
  const ids = targetIds(target).join(",");
  const { width, height, copies, details, qr } = options;

  useEffect(() => {
    if (ids === "" || width <= 0 || height <= 0) return;
    let cancelled = false;
    setState((s) => ({ ...s, isLoading: true }));

    const timer = setTimeout(() => {
      const chosen = ids.split(",");
      fetchBarcodeLabels(
        kind === "items" ? { itemIds: chosen } : { storageIds: chosen },
        { width, height, copies, details, qr },
      )
        .then(({ blob, withoutCode, withDetails }) => {
          if (cancelled) return;
          const previous = currentUrl.current;
          currentUrl.current = URL.createObjectURL(blob);
          setUrl(currentUrl.current);
          if (previous) URL.revokeObjectURL(previous);
          setState({ withoutCode, withDetails, isLoading: false, error: null });
        })
        .catch((error: unknown) => {
          if (cancelled) return;
          setState({
            withoutCode: 0,
            withDetails: null,
            isLoading: false,
            error: extractApiError(error, failedText),
          });
        });
    }, 400);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [kind, ids, width, height, copies, details, qr, failedText]);

  useEffect(
    () => () => {
      if (currentUrl.current) URL.revokeObjectURL(currentUrl.current);
    },
    [],
  );

  return { url, ...state };
}
