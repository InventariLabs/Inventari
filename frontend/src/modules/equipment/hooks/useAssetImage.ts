import { useMemo } from "react";
import { useEquipmentModels } from "@/modules/equipment/hooks/useEquipment";
import { getEquipmentMeta } from "@/modules/equipment/components/assetUtils";
import type { Item } from "@/types";

export interface AssetImage {
  url: string;
  /** True when the picture belongs to the model, not to this one unit. */
  fromModel: boolean;
}

/**
 * The picture to show for an asset.
 *
 * A batch of twenty identical laptops is created in one call with no place to
 * upload twenty photos, so every one of them showed the placeholder icon —
 * while the model they were created from carried a picture one screen away.
 * The model is what units share; its picture is theirs until one of them gets
 * its own, which always wins.
 */
export function useAssetImage(): (item: Item) => AssetImage | null {
  // The model's picture is a fallback for a unit with none of its own. A list
  // that failed leaves those units on the placeholder, as before the list
  // arrived — nothing is claimed — so it carries no empty default.
  const { data: models } = useEquipmentModels();

  const imageByModel = useMemo(() => {
    const map = new Map<string, string>();
    models?.forEach((model) => {
      if (model.image_url) map.set(model.id, model.image_url);
    });
    return map;
  }, [models]);

  return useMemo(
    () => (item: Item) => {
      if (item.image_url) return { url: item.image_url, fromModel: false };

      const modelId = getEquipmentMeta(item).model_id;
      if (typeof modelId !== "string") return null;

      const url = imageByModel.get(modelId);
      return url ? { url, fromModel: true } : null;
    },
    [imageByModel],
  );
}
