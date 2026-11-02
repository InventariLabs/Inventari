import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiErrorStatus, extractApiError } from "@/lib/errors";
import { useModules } from "@/contexts/ModulesContext";
import { useStoragesTree } from "@/hooks/queries/useStoragesTree";
import { useOfferedLocations } from "@/module-sdk";
import { usePostNewDocument } from "@/modules/warehouse/hooks/useDocuments";
import { useDocumentPartnerOptions } from "@/modules/warehouse/hooks/useDocumentPartnerOptions";
import { useDraftExtensions } from "@/modules/warehouse/hooks/useDraftExtensions";
import { useDocumentWorkspaceState } from "@/modules/warehouse/hooks/useDocumentWorkspaceState";
import {
  readLastUsedLocations,
  rememberLastUsedLocations,
} from "@/modules/warehouse/lib/lastUsedLocations";
import type {
  DocumentType,
  WarehouseDocument,
} from "@/modules/warehouse/types";

/**
 * Where a new action takes goods from before anyone chose: the place the last
 * one of its kind used, else the organization's only warehouse. A dispatch
 * or a move from a warehouse takes each line from the shelf it stands on, so
 * the whole warehouse is a sound default, not a guess at a shelf.
 */
function defaultSource(
  remembered: string | undefined,
  offeredIds: ReadonlySet<string>,
  roots: Array<{ id: string }>,
): string {
  if (remembered && offeredIds.has(remembered)) return remembered;
  return roots.length === 1 ? roots[0].id : "";
}

/**
 * The press may have landed with the answer lost on the way back: no answer
 * at all (the connection dropped) or a gateway that could not reach the
 * server (it is restarting). Sent again under the same key, it posts once.
 */
function answerWasLost(error: unknown): boolean {
  const status = apiErrorStatus(error);
  return status === null || status === 502 || status === 503 || status === 504;
}

/** Move focus to the first field the check refused, so the way to fix it is where the reader is. */
function focusFirstInvalid() {
  requestAnimationFrame(() => {
    document.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
  });
}

/**
 * The state of a one-screen action (issue, move) from the first line to the
 * posted document: the lines and places of the document form's workspace,
 * the partner picker, the check that runs once posting was asked for, and
 * the one call that creates and posts the document.
 *
 * Only what the chosen type carries is sent: the issue screen keeps one
 * draft while its purpose — and with it the type — changes, so a customer
 * picked for a delivery must not ride along on a write-off.
 */
export function useActionDraft(initialType: DocumentType) {
  const { t } = useTranslation("warehouse");
  const { isModuleEnabled } = useModules();
  const partnersEnabled = isModuleEnabled("partners");
  const workspace = useDocumentWorkspaceState({ initialType, partnersEnabled });
  const { docType, partnerId, sourceLocationId, setSourceLocationId } =
    workspace;
  // An issue and a move take stock off a shelf and put it down on another:
  // they are offered the places that may hold stock, never one another
  // module claims (a server rack, a workshop bench), whatever the
  // organization says its general lists should mix. Goods put there lie
  // where Occupancy and the labels never show them. The pickers search those
  // places on the server; this hook reads only the top of the tree, for the
  // default source.
  const { data: roots } = useStoragesTree(undefined, {
    excludeModuleContexts: true,
    depth: 1,
    counts: false,
  });
  const remembered = useMemo(
    () => readLastUsedLocations()[docType]?.source,
    [docType],
  );
  const { data: rememberedOffered, isError: offeredFailed } =
    useOfferedLocations([remembered]);
  const picker = useDocumentPartnerOptions({ type: docType }, partnerId);
  const [attempted, setAttempted] = useState(false);
  const [postError, setPostError] = useState<string | null>(null);
  const post = usePostNewDocument();
  // What other modules' fields on the screen save before the press is sent.
  const extensions = useDraftExtensions();
  // A press is named by a key the server remembers: the same body sent again
  // (a double click, a retry after the answer was lost) is answered with the
  // document the first send made, not a second one. Changing a line makes
  // another press, with a key of its own.
  const press = useRef<{ key: string; body: string } | null>(null);
  // A press that is waiting for a module to save its fields has sent nothing
  // yet, so the posting call cannot tell it is under way. The ref closes the
  // second press at once; the state is what the button shows.
  const preparing = useRef(false);
  const [isPreparing, setIsPreparing] = useState(false);

  // Once, when the places arrive: a later choice of "none" is the reader's.
  const sourceDefaulted = useRef(false);
  // A check that failed does not say the place is gone: it stays the default,
  // and the server refuses a place that may not be used when the press is sent.
  const rememberedKnown =
    !remembered || rememberedOffered !== undefined || offeredFailed;
  useEffect(() => {
    if (sourceDefaulted.current || roots === undefined || !rememberedKnown) {
      return;
    }
    sourceDefaulted.current = true;
    if (!sourceLocationId) {
      setSourceLocationId(
        defaultSource(
          remembered,
          new Set(
            offeredFailed && remembered ? [remembered] : rememberedOffered,
          ),
          roots,
        ),
      );
    }
  }, [
    roots,
    rememberedKnown,
    remembered,
    rememberedOffered,
    offeredFailed,
    sourceLocationId,
    setSourceLocationId,
  ]);

  // The blank row the workspace opens with is not a line anybody entered.
  const entered = workspace.lines.filter(
    (line) => !!line.item_id || !!line.name.trim(),
  );
  const errors = attempted
    ? workspace.validateForm(picker.selectedPartnerOffered)
    : {};

  const submit = (onPosted: (document: WarehouseDocument) => void) => {
    if (preparing.current) return;
    setAttempted(true);
    setPostError(null);
    if (entered.length === 0) {
      setPostError(t("lines.noLines"));
      return;
    }
    const refused = workspace.validateForm(picker.selectedPartnerOffered);
    if (Object.keys(refused).length > 0) {
      focusFirstInvalid();
      return;
    }
    const source = workspace.requiresSource ? sourceLocationId : "";
    const target = workspace.requiresTarget ? workspace.targetLocationId : "";
    const data = {
      ...workspace.toCreatePayload(),
      partner_id: docType === "OUT" ? partnerId || undefined : undefined,
      source_location_id: source || undefined,
      target_location_id: target || undefined,
    };
    const body = JSON.stringify(data);
    if (press.current?.body !== body) {
      press.current = { key: crypto.randomUUID(), body };
    }
    const key = press.current.key;
    const fail = (error: unknown) => {
      setPostError(
        answerWasLost(error)
          ? t("errors.postConnectionLost")
          : extractApiError(error, t("errors.postNowFailed")),
      );
    };
    const send = () =>
      post.mutate(
        { data, key },
        {
          onSuccess: (document) => {
            press.current = null;
            rememberLastUsedLocations(docType, source, target);
            onPosted(document);
          },
          onError: fail,
        },
      );
    // Without a contributor the press is sent in the same tick, as before.
    if (!extensions.hasCallbacks()) {
      send();
      return;
    }
    // A module's refusal never reached the server, so it is not a lost answer.
    preparing.current = true;
    setIsPreparing(true);
    extensions
      .runBeforeSubmit()
      .then(send, (error: unknown) => {
        setPostError(extractApiError(error, t("errors.postNowFailed")));
      })
      .finally(() => {
        preparing.current = false;
        setIsPreparing(false);
      });
  };

  return {
    workspace,
    picker,
    partnersEnabled,
    extensions,
    entered,
    errors,
    postError,
    isPosting: post.isPending || isPreparing,
    submit,
  };
}

export type ActionDraft = ReturnType<typeof useActionDraft>;
