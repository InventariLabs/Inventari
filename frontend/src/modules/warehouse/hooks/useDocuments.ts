import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useDocumentLineNames } from "./useDocumentLineNames";
import { useAppMutation } from "@/lib/api/mutationFactory";
import {
  documentsApi,
  type DocumentsListParams,
} from "@/modules/warehouse/api/documents";
import type {
  CorrectionCreate,
  DocumentCompletePayload,
  DocumentCreate,
  DocumentTrackingPayload,
  DocumentUpdate,
  RegisterParams,
  RegisterRowsParams,
  RegisterRowsResponse,
  ReturnCreate,
} from "@/modules/warehouse/types";
import { queryKeys } from "@/hooks/queries/keys";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";
import { invalidation } from "@/lib/api/invalidation";

export function useDocuments(params?: DocumentsListParams) {
  return useModuleQuery("warehouse", {
    queryKey: [...queryKeys.documents.all, params],
    queryFn: () => documentsApi.list(params),
  });
}

export function useDocument(id: string | undefined) {
  const query = useQuery({
    queryKey: queryKeys.documents.detail(id!),
    queryFn: () => documentsApi.getById(id!),
    enabled: !!id,
  });
  const named = useDocumentLineNames(query.data);
  return named === query.data ? query : { ...query, data: named };
}

/** The document as the server has it now, fetched on demand.
 *
 * For a form that was opened before something else wrote to the same
 * document — the line import does, through its own endpoint — so the screen
 * can take the new lines instead of saving over them.
 */
export function useFetchDocument() {
  const queryClient = useQueryClient();
  return useCallback(
    (id: string) =>
      queryClient.fetchQuery({
        queryKey: queryKeys.documents.detail(id),
        queryFn: () => documentsApi.getById(id),
      }),
    [queryClient],
  );
}

export function useCreateDocument() {
  return useAppMutation(
    ({ data, key }: { data: DocumentCreate; key?: string }) =>
      documentsApi.create(data, key),
    (qc) => {
      invalidation.documents(qc);
    },
  );
}

/** The one-screen actions: a whole document created and posted in one call. */
export function usePostNewDocument() {
  return useAppMutation(
    ({
      data,
      key,
      confirmSurplus,
    }: {
      data: DocumentCreate;
      key: string;
      confirmSurplus?: boolean;
    }) => documentsApi.postNew(data, key, confirmSurplus),
    (qc) => {
      invalidation.documents(qc);
      // A stop at approval moves the document into the approvers' queue.
      invalidation.notifications(qc);
    },
  );
}

export function useUpdateDocument() {
  return useAppMutation(
    ({ id, data }: { id: string; data: DocumentUpdate }) =>
      documentsApi.update(id, data),
    (qc, _data, { id }) => {
      // With the id, the document's own approval answer goes too: an edit can
      // move a draft across the approval threshold, and the confirm dialog
      // reads its sentence from that answer.
      invalidation.documents(qc, id);
    },
  );
}

export function useConfirmDocument() {
  return useAppMutation(
    (id: string) => documentsApi.confirm(id),
    (qc, _data, id) => {
      invalidation.documents(qc, id);
    },
  );
}

/** The one-step action: confirm and post the draft in one call. */
function usePostDocumentNow() {
  return useAppMutation(
    (vars: { id: string; data?: DocumentTrackingPayload }) =>
      documentsApi.postNow(vars.id, vars.data),
    (qc, _data, vars) => {
      invalidation.documents(qc, vars.id);
      // A one-step receipt may leave a backorder, and a stop at approval
      // moves the document between the queues and the notification list.
      invalidation.notifications(qc);
    },
  );
}

export function useImportOpeningStock() {
  return useAppMutation(
    ({
      file,
      mapping,
      targetLocationId,
    }: {
      file: File;
      mapping: unknown;
      targetLocationId: string;
    }) => documentsApi.importOpeningStock(file, mapping, targetLocationId),
    (qc) => {
      invalidation.documents(qc);
    },
  );
}

export function useDuplicateDocument() {
  return useAppMutation(
    (id: string) => documentsApi.duplicate(id),
    (qc) => {
      invalidation.documents(qc);
    },
  );
}

export function useCompleteDocument() {
  return useAppMutation(
    ({ id, data }: { id: string; data?: DocumentCompletePayload }) =>
      documentsApi.complete(id, data),
    (qc) => {
      invalidation.documents(qc);
    },
  );
}

export function useSetLineTarget() {
  return useAppMutation(
    ({
      docId,
      lineId,
      targetLocationId,
    }: {
      docId: string;
      lineId: string;
      targetLocationId: string | null;
    }) => documentsApi.setLineTarget(docId, lineId, targetLocationId),
    (qc) => {
      invalidation.documents(qc);
    },
  );
}

/** Write one module's fields on a saved document, or on one of its lines. */
export function useSetDocumentMetaData() {
  return useAppMutation(documentsApi.setMetaData, (qc) => {
    invalidation.documents(qc);
  });
}

export function useCancelDocument() {
  return useAppMutation(
    (id: string) => documentsApi.cancel(id),
    (qc) => {
      invalidation.documents(qc);
      // The server withdraws the document's open approval request with it,
      // which marks the "waiting for your decision" notice read.
      invalidation.notifications(qc);
    },
  );
}

/** Reverse a just-posted receipt, issue or move: the server writes the
 * correcting document and posts it, and the original names it from then on. */
export function useUndoDocument() {
  return useAppMutation(
    (id: string) => documentsApi.undo(id),
    (qc, _data, id) => {
      // The original's own answer goes too: its "reversed by" pointer is
      // written by the same call.
      invalidation.documents(qc, id);
    },
  );
}

export function useDeleteDocument() {
  return useAppMutation(
    (id: string) => documentsApi.delete(id),
    (qc) => {
      invalidation.documents(qc);
      // The server withdraws the document's open approval request with it,
      // which marks the "waiting for your decision" notice read.
      invalidation.notifications(qc);
    },
  );
}

export function useDocumentRegister(params: RegisterParams) {
  return useModuleQuery("warehouse", {
    queryKey: queryKeys.documents.register(params),
    queryFn: () => documentsApi.getRegisterSummary(params),
    extraEnabled: !!params.date_from && !!params.date_to,
  });
}

/** One group's documents, one page. The window filters travel
 * with the key, so a filter change starts a fresh page at offset 0. Pass
 * `enabled` when the reader must open something first — a collapsed group
 * needs no rows. */
export function useDocumentRegisterRows(
  params: RegisterRowsParams,
  enabled = true,
) {
  return useModuleQuery<RegisterRowsResponse>("warehouse", {
    queryKey: queryKeys.documents.registerRows(params),
    queryFn: () => documentsApi.getRegisterRows(params),
    extraEnabled: !!params.date_from && !!params.date_to && enabled,
  });
}

export function useCreateCorrection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: CorrectionCreate) => documentsApi.createCorrection(data),
    onSettled: () => {
      invalidation.documents(queryClient);
    },
  });
}

export function useDocumentCorrections(documentId: string) {
  return useQuery({
    queryKey: queryKeys.documents.corrections(documentId),
    queryFn: () => documentsApi.listCorrections(documentId),
    enabled: !!documentId,
  });
}

export function useCreateReturn() {
  return useAppMutation(
    ({ documentId, data }: { documentId: string; data: ReturnCreate }) =>
      documentsApi.createReturn(documentId, data),
    (qc) => {
      invalidation.documents(qc);
    },
  );
}

export function useDocumentWorkflow() {
  const createDocument = useCreateDocument();
  const updateDocument = useUpdateDocument();
  const confirmDocument = useConfirmDocument();
  const completeDocument = useCompleteDocument();
  const postDocumentNow = usePostDocumentNow();
  const cancelDocument = useCancelDocument();
  const deleteDocument = useDeleteDocument();
  const undoDocument = useUndoDocument();

  return {
    createDocument,
    updateDocument,
    confirmDocument,
    completeDocument,
    postDocumentNow,
    cancelDocument,
    deleteDocument,
    undoDocument,
    isSavingDraft: createDocument.isPending || updateDocument.isPending,
    isTransitionPending:
      confirmDocument.isPending ||
      completeDocument.isPending ||
      postDocumentNow.isPending ||
      cancelDocument.isPending ||
      deleteDocument.isPending ||
      undoDocument.isPending,
  };
}
