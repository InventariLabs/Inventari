import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/Badge";
import type { PickDocumentGroup } from "./documentGroups";

interface Props {
  groups: PickDocumentGroup[];
}

const statusVariant = {
  picking: "secondary",
  short: "warning",
  all_picked: "success",
} as const;

/** Where each dispatch of a multi-document session stands. */
export default function WmsPickDocumentProgress({ groups }: Props) {
  const { t } = useTranslation("warehouse");
  return (
    <ul
      aria-label={t("picking.documents.progress_label")}
      className="flex flex-wrap gap-2 px-4 py-2 border-b border-border shrink-0"
    >
      {groups.map((group) => (
        <li key={group.documentId}>
          <Badge variant={statusVariant[group.status]}>
            {group.number} · {group.resolved}/{group.total}
          </Badge>
        </li>
      ))}
    </ul>
  );
}
