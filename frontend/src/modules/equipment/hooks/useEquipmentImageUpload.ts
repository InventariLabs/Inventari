import { useState } from "react";
import { itemsApi } from "@/lib/api/items";

/**
 * Owns the image state of the equipment form (file selection, delete flag,
 * the currently persisted image URL) and applies the pending changes after
 * the item itself is saved.
 */
export function useEquipmentImageUpload() {
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [deleteImageFlag, setDeleteImageFlag] = useState(false);
  const [currentImageUrl, setCurrentImageUrl] = useState<string | null>(null);

  const applyImageChanges = async (itemId: string) => {
    if (deleteImageFlag) {
      await itemsApi.deleteImage(itemId);
    }
    if (imageFile) {
      await itemsApi.uploadImage(itemId, imageFile);
    }
  };

  return {
    imageFile,
    setImageFile,
    deleteImageFlag,
    setDeleteImageFlag,
    currentImageUrl,
    setCurrentImageUrl,
    applyImageChanges,
  };
}
