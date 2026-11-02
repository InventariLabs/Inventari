import type { SlotDataMap } from "@/lib/moduleRegistry";
import AddItemModal from "../AddItemModal";

type Props = { data: SlotDataMap["shopping_list_add_item"] };

export default function AddItemModalSlot({ data }: Props) {
  return (
    <AddItemModal
      listId={data.listId}
      onClose={data.onClose}
      onSuccess={data.onSuccess}
    />
  );
}
