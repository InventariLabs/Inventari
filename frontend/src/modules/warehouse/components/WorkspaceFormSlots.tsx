import { TypedSlot } from "@/components/Slot";
import type {
  DocumentFormAction,
  RegisterBeforeSubmit,
} from "@/lib/moduleRegistry";
import {
  receiptLineView,
  type ReceiptDraftLine,
} from "@/modules/warehouse/components/documentFormShared";
import type { DocumentWorkspace } from "@/modules/warehouse/hooks/useDocumentWorkspaceState";

/** What a screen built on the document workspace tells other modules' fields. */
interface WorkspaceSlotProps {
  action: DocumentFormAction;
  workspace: DocumentWorkspace;
  registerBeforeSubmit: RegisterBeforeSubmit;
}

/**
 * Other modules' fields among the document-level fields. What they write
 * goes into the workspace and is sent with the document.
 */
export function WorkspaceFormExtra({
  action,
  workspace,
  registerBeforeSubmit,
  partnerId,
  lines,
}: WorkspaceSlotProps & {
  partnerId: string | null;
  /** The lines the screen holds. */
  lines: ReceiptDraftLine[];
}) {
  return (
    <TypedSlot
      name="document_form_extra"
      data={{
        action,
        documentType: workspace.docType,
        partnerId,
        lines: lines.map(receiptLineView),
        metaData: workspace.metaData,
        setMetaData: workspace.setMetaData,
        registerBeforeSubmit,
      }}
    />
  );
}

/** The editor's `renderLineExtra` for a screen built on the workspace. */
export function lineExtraFor(
  action: DocumentFormAction,
  workspace: DocumentWorkspace,
  registerBeforeSubmit: RegisterBeforeSubmit,
) {
  return function renderLineExtra(line: ReceiptDraftLine) {
    return (
      <WorkspaceLineExtra
        action={action}
        workspace={workspace}
        registerBeforeSubmit={registerBeforeSubmit}
        line={line}
      />
    );
  };
}

/** Other modules' fields under one line, written onto that line. */
function WorkspaceLineExtra({
  action,
  workspace,
  registerBeforeSubmit,
  line,
}: WorkspaceSlotProps & { line: ReceiptDraftLine }) {
  return (
    <TypedSlot
      name="document_line_form_extra"
      data={{
        action,
        documentType: workspace.docType,
        line: receiptLineView(line),
        setMetaData: (module, values) =>
          workspace.setLineMetaData(line._key, module, values),
        registerBeforeSubmit,
      }}
    />
  );
}
