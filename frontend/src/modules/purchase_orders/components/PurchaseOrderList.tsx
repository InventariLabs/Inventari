import { useMediaQuery } from "@/hooks/useMediaQuery";
import type { PurchaseOrderRow } from "@/modules/purchase_orders/types/purchase-orders";
import PurchaseOrderListItem from "./PurchaseOrderListItem";
import { PurchaseOrderTable } from "./PurchaseOrderTable";

interface Props {
  purchaseOrders: PurchaseOrderRow[];
  canWrite: boolean;
  canManage: boolean;
  onView: (po: PurchaseOrderRow) => void;
  onEdit: (po: PurchaseOrderRow) => void;
  onConfirm: (po: PurchaseOrderRow) => void;
  onCancel: (po: PurchaseOrderRow) => void;
}

/** A table from `md` up, the card stack on a phone (§14.1). */
export function PurchaseOrderList(props: Props) {
  const isPhone = useMediaQuery("(max-width: 767px)");
  if (!isPhone) return <PurchaseOrderTable {...props} />;
  const {
    purchaseOrders,
    onView,
    onEdit,
    onConfirm,
    onCancel,
    canWrite,
    canManage,
  } = props;
  return (
    <div className="space-y-3">
      {purchaseOrders.map((po) => (
        <PurchaseOrderListItem
          key={po.id}
          purchaseOrder={po}
          canWrite={canWrite}
          canManage={canManage}
          onView={() => onView(po)}
          onEdit={() => onEdit(po)}
          onConfirm={() => onConfirm(po)}
          onCancel={() => onCancel(po)}
        />
      ))}
    </div>
  );
}
