import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { itemsApi } from "@/lib/api/items";
import { invalidation } from "@/lib/api/invalidation";
import { queryKeys } from "@/hooks/queries/keys";
import { extractApiError } from "@/lib/errors";

/**
 * The photo picked in a product's edit sheet. It is held until Save and
 * stored after the item itself: the update carries the picture the sheet
 * opened with, so a photo stored at pick time would be written over by that
 * stale value. Closing the sheet drops it like any other edit.
 */
export function usePickedItemImage(
  itemId: string,
  item: { image_url?: string | null } | undefined,
) {
  const savedUrl = item?.image_url;
  const queryClient = useQueryClient();
  const [picked, setPicked] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);

  // A record reloaded while a picked photo waits for Save keeps showing the
  // photo that was picked.
  useEffect(() => {
    if (savedUrl && !picked) setPreview(savedUrl);
  }, [savedUrl, picked]);

  const pick = (file: File) => {
    setPicked(file);
    setPreview(URL.createObjectURL(file));
  };

  /** Stores the picked photo, if there is one, and then calls `done`. When the
   * server refuses it `refused` gets the sentence to show instead, and the
   * sheet shows the product's own picture again so the same file can be
   * picked once more. */
  const store = async (
    fallback: string,
    refused: (message: string) => void,
    done: () => void,
  ) => {
    if (picked) {
      try {
        await itemsApi.uploadImage(itemId, picked);
      } catch (error) {
        setPicked(null);
        setPreview(savedUrl ?? null);
        refused(extractApiError(error, fallback));
        return;
      }
      queryClient.invalidateQueries({
        queryKey: queryKeys.items.detail(itemId),
      });
      invalidation.items(queryClient);
    }
    done();
  };

  return { preview, setPreview, hasPicked: picked !== null, pick, store };
}
