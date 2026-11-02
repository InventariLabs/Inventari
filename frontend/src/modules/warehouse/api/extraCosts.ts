/**
 * Freight, duty and insurance on a receipt.
 *
 * Read-write while the receipt is unposted; afterwards the API refuses and
 * says why, because the goods may already have left and there is nothing
 * left to charge.
 */
import { api } from "@/lib/api/client";
import type { components } from "@/types/api-generated";

export type ExtraCostsView = components["schemas"]["ExtraCostsView"];
export type ExtraCostKind = components["schemas"]["ExtraCostKind"];
export type ExtraCostAllocation = components["schemas"]["ExtraCostAllocation"];

export interface ExtraCostInput {
  kind: ExtraCostKind;
  amount: string;
  allocation_method: ExtraCostAllocation;
  note?: string;
}

export const extraCostsApi = {
  get: async (documentId: string): Promise<ExtraCostsView> => {
    const response = await api.get<ExtraCostsView>(
      `/warehouse/documents/${documentId}/extra-costs`,
    );
    return response.data;
  },

  add: async (
    documentId: string,
    input: ExtraCostInput,
  ): Promise<ExtraCostsView> => {
    const response = await api.post<ExtraCostsView>(
      `/warehouse/documents/${documentId}/extra-costs`,
      input,
    );
    return response.data;
  },

  remove: async (
    documentId: string,
    costId: string,
  ): Promise<ExtraCostsView> => {
    const response = await api.delete<ExtraCostsView>(
      `/warehouse/documents/${documentId}/extra-costs/${costId}`,
    );
    return response.data;
  },
};
