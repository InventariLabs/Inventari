import { api, getEveryPage, type Page } from "@/lib/api/client";
import type { components } from "@/types/api-generated";

/**
 * The print queue of the `printing` module: labels sent from the app to a
 * printer, printed by the Inventari Print Agent running next to it.
 *
 * Shared because every screen that prints labels — the label pool, a storage
 * location, equipment — offers "Send to printer", and none of them owns the
 * printer.
 */

/** A printer, as its local agent announced it. */
export type PrintAgent = components["schemas"]["PrintAgentResponse"];

/** A job in the queue, newest first in the list the module returns. */
export type PrintJob = components["schemas"]["PrintJobResponse"];

export type PrintJobStatus = PrintJob["status"];

/** What to print: exactly one kind of target. `itemIds` prints products'
 *  barcode labels; `packageLabel` one package of a dispatch, whose label the
 *  warehouse words and queues. */
export type PrintTarget =
  | { labelIds: string[] }
  | { shortCodes: string[] }
  | { storageIds: string[] }
  | { itemIds: string[] }
  | { packageLabel: { documentId: string; packageId: string } };

/** The label download's options, so the printed strip matches the file. */
export interface PrintOptions {
  /** One caption for every label instead of each label's own. */
  caption?: string;
  qrOnly?: boolean;
  /** The short code printed small under the QR. */
  showCode?: boolean;
  copies?: number;
  /** A product label's lot and expiry line. */
  details?: boolean;
  /** Storage locations as shelf labels: the code in Code 128, not a QR. */
  bars?: boolean;
  /** With `bars`: a QR beside them as well. */
  qr?: boolean;
  /** The label's size in mm. The printer has none of its own: its agent
   *  fits this label to it. */
  width?: number;
  height?: number;
}

function targetBody(target: Exclude<PrintTarget, { packageLabel: unknown }>) {
  if ("labelIds" in target) return { label_ids: target.labelIds };
  if ("shortCodes" in target) return { short_codes: target.shortCodes };
  if ("itemIds" in target) return { item_ids: target.itemIds };
  return { location_ids: target.storageIds };
}

export const printQueueApi = {
  agents: async (): Promise<PrintAgent[]> => {
    return getEveryPage<PrintAgent>("/printing/agents");
  },

  jobs: async (): Promise<PrintJob[]> => {
    // The newest page only: the panel shows the latest jobs, not the history.
    const response = await api.get<Page<PrintJob>>("/printing/jobs");
    return response.data.items;
  },

  queue: async (vars: {
    target: PrintTarget;
    agentId?: string;
    options?: PrintOptions;
  }): Promise<PrintJob | undefined> => {
    // A package's label is worded by the warehouse, which queues it; the job
    // is listed with the rest of the queue.
    if ("packageLabel" in vars.target) {
      const { documentId, packageId } = vars.target.packageLabel;
      await api.post(
        `/warehouse/documents/${documentId}/packages/${packageId}/label/print`,
        {
          agent_id: vars.agentId ?? null,
          width_mm: vars.options?.width ?? 50,
          height_mm: vars.options?.height ?? 24,
        },
      );
      return undefined;
    }
    const response = await api.post<PrintJob>("/printing/jobs", {
      ...targetBody(vars.target),
      agent_id: vars.agentId ?? null,
      caption: vars.options?.caption || null,
      qr_only: vars.options?.qrOnly ?? false,
      show_code: vars.options?.showCode ?? false,
      copies: vars.options?.copies ?? 1,
      ...(vars.options?.details !== undefined && {
        details: vars.options.details,
      }),
      ...(vars.options?.bars && { bars: true, qr: vars.options.qr ?? false }),
      width_mm: vars.options?.width ?? 50,
      height_mm: vars.options?.height ?? 24,
    });
    return response.data;
  },

  retry: async (jobId: string): Promise<PrintJob> => {
    const response = await api.post<PrintJob>(`/printing/jobs/${jobId}/retry`);
    return response.data;
  },
};
