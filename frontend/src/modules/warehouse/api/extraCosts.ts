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

export type CostVarianceList = components["schemas"]["CostVariancesList"];

export interface CostVarianceInput {
  kind: ExtraCostKind;
  amount: string;
  reason: string;
  occurred_on?: string;
}

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

  /**
   * A cost that reached no product: kept with its reason and reported, and
   * never part of any stock value.
   */
  addVariance: async (
    documentId: string,
    input: CostVarianceInput,
  ): Promise<ExtraCostsView> => {
    const response = await api.post<ExtraCostsView>(
      `/warehouse/documents/${documentId}/cost-variances`,
      input,
    );
    return response.data;
  },

  removeVariance: async (
    documentId: string,
    varianceId: string,
  ): Promise<ExtraCostsView> => {
    const response = await api.delete<ExtraCostsView>(
      `/warehouse/documents/${documentId}/cost-variances/${varianceId}`,
    );
    return response.data;
  },

  listVariances: async (page: {
    limit: number;
    offset: number;
  }): Promise<CostVarianceList> => {
    const response = await api.get<CostVarianceList>(
      "/warehouse/cost-variances",
      { params: page },
    );
    return response.data;
  },
};
