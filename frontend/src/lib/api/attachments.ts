import { prepareImageUpload } from "@/lib/imageUtils";
import { api, getEveryPage } from "./client";
import { assertFileSize } from "@/utils/fileValidation";
import type { ItemAttachment } from "@/types";

export const attachmentsApi = {
  upload: async (itemId: string, file: File): Promise<ItemAttachment> => {
    const upload = await prepareImageUpload(file, { imageOnly: false });
    assertFileSize(upload);
    const formData = new FormData();
    formData.append("file", upload);
    const response = await api.post<ItemAttachment>(
      `/items/${itemId}/attachments`,
      formData,
    );
    return response.data;
  },

  list: async (itemId: string): Promise<ItemAttachment[]> => {
    return getEveryPage<ItemAttachment>(`/items/${itemId}/attachments`);
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/attachments/${id}`);
  },
};
