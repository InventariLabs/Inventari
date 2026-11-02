import { api } from "@/lib/api/client";
import { assertFileSize } from "@/utils/fileValidation";
import type { VisionExtractResult } from "@/types";

/**
 * Image recognition, which is a Core subsystem (docs/subsystems/VISION_AI.md).
 *
 * It used to live inside the stats module, so three other modules reached
 * across a module boundary to scan a photo — nutrition, quick-add and the
 * scan page. Nothing about vision belongs to statistics; the endpoint is
 * Core's, and so is this client.
 */
export const visionApi = {
  extract: async (
    files: File[],
    // What the label was printed for. Decides which modules add fields to
    // the reading — an asset sticker is never asked about a nutrition table.
    // This replaced a storage type that defaulted to a pantry, which was one
    // vertical's furniture standing in for the scan's intent.
    context_tag?: string,
  ): Promise<VisionExtractResult> => {
    for (const f of files) {
      assertFileSize(f);
    }
    const formData = new FormData();
    files.forEach((file) => formData.append("images", file));
    if (context_tag) formData.append("context_tag", context_tag);
    const response = await api.post<VisionExtractResult>(
      "/vision/extract",
      formData,
    );
    return response.data;
  },

  extractNutrition: async (file: File): Promise<Record<string, unknown>> => {
    assertFileSize(file);
    const formData = new FormData();
    formData.append("file", file);
    const response = await api.post("/vision/extract-nutrition", formData, {});
    return response.data;
  },
};
