import { useState } from "react";
import { useTranslation } from "react-i18next";
import i18next from "i18next";
import { Printer } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { runWithToast } from "@/lib/api/runWithToast";
import { downloadBlob } from "@/utils/helpers";
import { documentsPickingApi } from "@/modules/warehouse/api/documents_picking";

interface Props {
  /** The dispatch the list is for; for a session, any document of it. */
  documentId: string;
  /** The session whose lines, in the screen's order, the list prints. */
  sessionId?: string;
  /** The number the file is named after. */
  number: string;
  /** A corner of a full-screen sheet gets the icon alone. */
  iconOnly?: boolean;
}

/** The paper pick list: the lines in the order they are walked, the shelf first. */
export function PickListButton({
  documentId,
  sessionId,
  number,
  iconOnly = false,
}: Props) {
  const { t } = useTranslation("warehouse");
  const [pending, setPending] = useState(false);
  const label = t("picking.print_list");

  const print = async () => {
    setPending(true);
    await runWithToast(
      async () => {
        const lang = i18next.language || "en";
        const blob = sessionId
          ? await documentsPickingApi.sessionPickListPdf(
              documentId,
              sessionId,
              lang,
            )
          : await documentsPickingApi.dispatchPickListPdf(documentId, lang);
        downloadBlob(blob, `pick_list_${number.replace(/[/\s]/g, "-")}.pdf`);
      },
      { errorFallback: t("picking.print_list_failed") },
    );
    setPending(false);
  };

  return (
    <Button
      variant={iconOnly ? "ghost" : "outline"}
      size={iconOnly ? "icon" : "sm"}
      leftIcon={iconOnly ? undefined : <Printer size={15} />}
      isLoading={pending}
      onClick={() => void print()}
      aria-label={iconOnly ? label : undefined}
      title={iconOnly ? label : undefined}
    >
      {iconOnly ? <Printer size={18} /> : label}
    </Button>
  );
}
