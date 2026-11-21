import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api/client";
import { extractApiError } from "@/lib/errors";

/** Whose labels with bars: products', shelves' — a location's code in
 *  Code 128 for a 1D scanner — or batches', the batch's own code in bars
 *  with the day it was made and its best-before. */
export type BarcodeLabelTarget =
  { itemIds: string[] } | { storageIds: string[] } | { lotIds: string[] };

type TargetKind = "items" | "storages" | "lots";

function targetKind(target: BarcodeLabelTarget): TargetKind {
  if ("itemIds" in target) return "items";
  if ("lotIds" in target) return "lots";
  return "storages";
}

function targetOf(kind: TargetKind, ids: string[]): BarcodeLabelTarget {
  if (kind === "items") return { itemIds: ids };
  if (kind === "lots") return { lotIds: ids };
  return { storageIds: ids };
}

export interface BarcodeLabelOptions {
  width: number;
  height: number;
  copies: number;
  /** A product label's lot and expiry line, when the record has them. */
  details: boolean;
  /** A shelf label's QR beside the bars, for a phone camera. */
  qr: boolean;
  /** A made product's ingredient list and allergens, on a product's or a
   *  batch's label. */
  composition: boolean;
}

export interface BarcodeLabelFile {
  blob: Blob;
  /** Chosen products or locations left out because they carry no code. */
  withoutCode: number;
  /** Products among the printed ones that have a lot or an expiry date to
   *  print, or null when the server does not say (shelf labels). */
  withDetails: number | null;
  /** Labels of a made product, which have an ingredient list to print, or
   *  null when the server does not say (shelf labels). */
  withComposition: number | null;
}

function targetIds(target: BarcodeLabelTarget): string[] {
  if ("itemIds" in target) return target.itemIds;
  if ("lotIds" in target) return target.lotIds;
  return target.storageIds;
}

function postLabels(target: BarcodeLabelTarget, options: BarcodeLabelOptions) {
  const size = {
    width_mm: options.width,
    height_mm: options.height,
    copies: options.copies,
  };
  const asBlob = { responseType: "blob" } as const;
  if ("itemIds" in target)
    return api.post<Blob>(
      "/printing/product-labels/png",
      {
        item_ids: target.itemIds,
        details: options.details,
        composition: options.composition,
        ...size,
      },
      asBlob,
    );
  if ("lotIds" in target)
    return api.post<Blob>(
      "/printing/lot-labels/png",
      { lot_ids: target.lotIds, composition: options.composition, ...size },
      asBlob,
    );
  return api.post<Blob>(
    "/printing/location-labels/png",
    { location_ids: target.storageIds, qr: options.qr, ...size },
    asBlob,
  );
}

/** The labels as one PNG — the preview and the download. */
export async function fetchBarcodeLabels(
  target: BarcodeLabelTarget,
  options: BarcodeLabelOptions,
): Promise<BarcodeLabelFile> {
  const response = await postLabels(target, options);
  const withDetails = response.headers["x-labels-with-details"];
  const withComposition = response.headers["x-labels-with-composition"];
  return {
    blob: response.data,
    withoutCode: Number(response.headers["x-labels-without-code"] ?? 0),
    withDetails: withDetails === undefined ? null : Number(withDetails),
    withComposition:
      withComposition === undefined ? null : Number(withComposition),
  };
}

interface BarcodeLabelPreview {
  /** Object URL of the rendered sheet, or null while there is nothing to show. */
  url: string | null;
  withoutCode: number;
  withDetails: number | null;
  withComposition: number | null;
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
  /** The reader's names for the fields a refusal can name, by API key. */
  fieldNames?: Record<string, string>,
): BarcodeLabelPreview {
  const [state, setState] = useState<Omit<BarcodeLabelPreview, "url">>({
    withoutCode: 0,
    withDetails: null,
    withComposition: null,
    isLoading: false,
    error: null,
  });
  const [url, setUrl] = useState<string | null>(null);
  const currentUrl = useRef<string | null>(null);
  // Names a refusal only; the request does not depend on them, so a new
  // object each render must not re-run it.
  const fieldNamesRef = useRef(fieldNames);
  useEffect(() => {
    fieldNamesRef.current = fieldNames;
  }, [fieldNames]);
  const kind = targetKind(target);
  const ids = targetIds(target).join(",");
  // A batch prints one label per unit made — up to two hundred of the same
  // label. The preview shows one; the download and the printer get them all.
  const { width, height, details, qr, composition } = options;
  const copies = kind === "lots" ? 1 : options.copies;

  useEffect(() => {
    if (ids === "" || width <= 0 || height <= 0) return;
    let cancelled = false;
    setState((s) => ({ ...s, isLoading: true }));

    const timer = setTimeout(() => {
      const chosen = ids.split(",");
      fetchBarcodeLabels(targetOf(kind, chosen), {
        width,
        height,
        copies,
        details,
        qr,
        composition,
      })
        .then(({ blob, withoutCode, withDetails, withComposition }) => {
          if (cancelled) return;
          const previous = currentUrl.current;
          currentUrl.current = URL.createObjectURL(blob);
          setUrl(currentUrl.current);
          if (previous) URL.revokeObjectURL(previous);
          setState({
            withoutCode,
            withDetails,
            withComposition,
            isLoading: false,
            error: null,
          });
        })
        .catch((error: unknown) => {
          if (cancelled) return;
          // What the labels have to print is still known: a list that does
          // not fit this size keeps its option, so it can be turned off.
          setState((s) => ({
            withoutCode: 0,
            withDetails: null,
            withComposition: s.withComposition,
            isLoading: false,
            error: extractApiError(error, failedText, fieldNamesRef.current),
          }));
        });
    }, 400);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [kind, ids, width, height, copies, details, qr, composition, failedText]);

  useEffect(
    () => () => {
      if (currentUrl.current) URL.revokeObjectURL(currentUrl.current);
    },
    [],
  );

  return { url, ...state };
}
