import { useTranslation } from "react-i18next";
import { useActiveShoppingList } from "../../hooks/useShoppingLists";
import DashboardShoppingList from "../DashboardShoppingList";

/**
 * The active list's progress beside the dashboard's recent moves. Nothing
 * until the list is read, so the card never flashes an empty state that the
 * answer then contradicts.
 */
export default function DashboardShoppingListSlot() {
  const { t } = useTranslation("common");
  const { data: activeShoppingList } = useActiveShoppingList();
  if (activeShoppingList === undefined) return null;
  return (
    <DashboardShoppingList activeShoppingList={activeShoppingList} t={t} />
  );
}
