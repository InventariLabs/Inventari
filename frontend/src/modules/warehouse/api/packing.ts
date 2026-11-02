/**
 * Packing a picked dispatch: packages, what each holds, the slip and the label.
 *
 * Every write answers with the whole packing view, so the screen takes what
 * is left to pack from the same answer that says the write landed.
 */
import { api } from "@/lib/api/client";
import type { components } from "@/types/api-generated";

export type PackingView = components["schemas"]["PackingView"];
export type PackageOut = components["schemas"]["PackageOut"];
export type PackingLineOut = components["schemas"]["PackingLineOut"];

export const packingApi = {
  get: async (documentId: string): Promise<PackingView> => {
    const response = await api.get<PackingView>(
      `/warehouse/documents/${documentId}/packages`,
    );
    return response.data;
  },

  create: async (documentId: string): Promise<PackingView> => {
    const response = await api.post<PackingView>(
      `/warehouse/documents/${documentId}/packages`,
      {},
    );
    return response.data;
  },

  packAll: async (documentId: string): Promise<PackingView> => {
    const response = await api.post<PackingView>(
      `/warehouse/documents/${documentId}/packages/pack-all`,
    );
    return response.data;
  },

  /** A weight in kilograms, or `null` to clear it. */
  setWeight: async (
    documentId: string,
    packageId: string,
    weightKg: string | null,
  ): Promise<PackingView> => {
    const response = await api.patch<PackingView>(
      `/warehouse/documents/${documentId}/packages/${packageId}`,
      { weight_kg: weightKg },
    );
    return response.data;
  },

  /** How much of the line the package holds from now on; zero takes it out. */
  setLine: async (
    documentId: string,
    packageId: string,
    lineId: string,
    quantity: string,
  ): Promise<PackingView> => {
    const response = await api.put<PackingView>(
      `/warehouse/documents/${documentId}/packages/${packageId}/lines/${lineId}`,
      { quantity },
    );
    return response.data;
  },

  scan: async (
    documentId: string,
    packageId: string,
    code: string,
  ): Promise<PackingView> => {
    const response = await api.post<PackingView>(
      `/warehouse/documents/${documentId}/packages/${packageId}/scan`,
      { code },
    );
    return response.data;
  },

  remove: async (
    documentId: string,
    packageId: string,
  ): Promise<PackingView> => {
    const response = await api.delete<PackingView>(
      `/warehouse/documents/${documentId}/packages/${packageId}`,
    );
    return response.data;
  },

  /** The slip of one package, or of every package when none is named. */
  slipPdf: async (
    documentId: string,
    packageId: string | null,
    lang: string,
  ): Promise<Blob> => {
    const config = { params: { lang }, responseType: "blob" as const };
    const response = packageId
      ? await api.get<Blob>(
          `/warehouse/documents/${documentId}/packages/${packageId}/packing-slip`,
          config,
        )
      : await api.get<Blob>(
          `/warehouse/documents/${documentId}/packing-slip`,
          config,
        );
    return response.data;
  },

  labelPng: async (documentId: string, packageId: string): Promise<Blob> => {
    const response = await api.get<Blob>(
      `/warehouse/documents/${documentId}/packages/${packageId}/label`,
      { responseType: "blob" },
    );
    return response.data;
  },
};
