import { useState } from "react";
import { itemsApi } from "@/lib/api/items";

/**
 * Owns the image state of the equipment form (file selection, delete flag,
 * the currently persisted image URL) and runs the pending changes after
 * the item itself is saved.
 */
export function useEquipmentImageUpload() {
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [deleteImageFlag, setDeleteImageFlag] = useState(false);
  const [currentImageUrl, setCurrentImageUrl] = useState<string | null>(null);

  // Two steps, kept apart: the form words a refusal by the step that was
  // refused, and a removal is not an upload.
  const removeImage = (itemId: string) => itemsApi.deleteImage(itemId);
  const uploadImage = (itemId: string, file: File) =>
    itemsApi.uploadImage(itemId, file);

  return {
    imageFile,
    setImageFile,
    deleteImageFlag,
    setDeleteImageFlag,
    currentImageUrl,
    setCurrentImageUrl,
    removeImage,
    uploadImage,
  };
}
