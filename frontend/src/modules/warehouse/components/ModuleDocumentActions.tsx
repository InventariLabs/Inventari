import { useState, type ComponentProps } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { PickListButton } from "@/modules/warehouse/components/picking/PickListButton";
import { DocumentActionButtons } from "@/modules/warehouse/components/DocumentActionButtons";
import { workingStatus } from "@/modules/warehouse/components/documentApprovalGate";
import { queryKeys } from "@/hooks/queries/keys";
import { useCanWrite } from "@/hooks/useCanWrite";
import { extractApiError } from "@/lib/errors";
import {
  toDocumentView,
  useDocumentContributions,
} from "@/modules/warehouse/hooks/useDocumentContributions";
import type { WarehouseDocument } from "@/modules/warehouse/types";

/**
 * The buttons enabled modules add to a document's action row.
 *
 * Offered to a reader who may write documents, like the row's own actions.
 * One press at a time; when it resolves the document is read again, so what
 * the module changed — a field it filled, a hold it lifted — shows at once.
 * The module's own sentence says how it went, a refusal's included.
 */
export function ModuleDocumentActions({ doc }: { doc: WarehouseDocument }) {
  const { t } = useTranslation();
  const canWrite = useCanWrite("warehouse");
  const { actions } = useDocumentContributions();
  const queryClient = useQueryClient();
  const [running, setRunning] = useState<string | null>(null);

  if (!canWrite) return null;
  const view = toDocumentView(doc);
  const offered = actions.filter(
    (action) => !action.isAvailable || action.isAvailable(view),
  );

  return (
    <>
      {offered.map((action) => {
        const id = `${action.moduleName}:${action.key}`;
        const Icon = action.icon;
        const press = async () => {
          setRunning(id);
          try {
            const outcome = await action.run(view);
            if (outcome) toast.success(t(outcome));
            await queryClient.invalidateQueries({
              queryKey: queryKeys.documents.detail(doc.id),
            });
          } catch (error: unknown) {
            toast.error(extractApiError(error, t("common:errors.generic")));
          } finally {
            setRunning(null);
          }
        };
        return (
          <Button
            key={id}
            variant="outline"
            size="sm"
            leftIcon={Icon ? <Icon size={15} /> : undefined}
            onClick={() => void press()}
            disabled={running !== null}
          >
            {t(action.label)}
          </Button>
        );
      })}
    </>
  );
}

type HeaderActionsProps = Omit<
  ComponentProps<typeof DocumentActionButtons>,
  "isDraft" | "isConfirmed" | "docStatus" | "docType"
> & { doc: WarehouseDocument };

/**
 * A document page's action row: the warehouse's own actions, read off the
 * document's state, then what enabled modules add after them.
 */
export function DocumentHeaderActions({ doc, ...actions }: HeaderActionsProps) {
  return (
    <div className="flex gap-2 flex-wrap">
      <DocumentActionButtons
        isDraft={doc.status === "DRAFT"}
        isConfirmed={workingStatus(doc) === "CONFIRMED"}
        docStatus={workingStatus(doc)}
        docType={doc.type}
        isReversed={!!doc.reversed_by_id}
        {...actions}
      />
      {actions.canStartPicking && (
        <PickListButton documentId={doc.id} number={doc.number} />
      )}
      <ModuleDocumentActions doc={doc} />
    </div>
  );
}
