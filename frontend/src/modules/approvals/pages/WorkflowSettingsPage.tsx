import {
  useCallback,
  useMemo,
  useState,
  useEffect,
  type FormEvent,
} from "react";
import { toast } from "sonner";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { Info, Pencil, Plus, Power, Trash2 } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import {
  WorkflowSwitchOffDialog,
  type SwitchOffMode,
} from "@/modules/approvals/components/WorkflowSwitchOffDialog";
import { DynamicIcon } from "@/components/ui/DynamicIcon";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useFormGuard } from "@/hooks/useFormGuard";
import { InlineQueryError, QueryFailure } from "@/components/ui/QueryResult";
import { extractApiError, extractApiErrorCode } from "@/lib/errors";
import { cn } from "@/lib/utils";
import { ApprovalWorkflowEditor } from "@/modules/approvals/components/ApprovalWorkflowEditor";
import { ApprovalDeadEndNotice } from "@/modules/approvals/components/ApprovalDeadEndNotice";
import { WorkflowActivationDialog } from "@/modules/approvals/components/WorkflowActivationDialog";
import { WorkflowScopeLine } from "@/modules/approvals/components/WorkflowScopeLine";
import { WorkflowRequestersLine } from "@/modules/approvals/components/WorkflowRequestersLine";
import { RequesterScopeField } from "@/modules/approvals/components/RequesterScopeField";
import {
  requesterScopeNamesSomebody,
  type RequesterScope,
} from "@/modules/approvals/workflowRequesters";
import { STAGE_UNSOLVABLE_CODE } from "@/modules/approvals/api/approvals";
import {
  useCanConfigureWorkflows,
  useCanReadWorkflows,
} from "@/modules/approvals/hooks/useApprovalPermissions";
import { useOrgMembers } from "@/modules/approvals/hooks/useOrgMembers";
import {
  useApprovalWorkflows,
  useCreateWorkflow,
  useDeleteWorkflow,
  useUpdateWorkflow,
} from "@/modules/approvals/hooks/useApprovalWorkflows";
import type {
  ApprovalWorkflow,
  StageDefinition,
  WorkflowCreateInput,
} from "@/modules/approvals/api/approvals";
import {
  stageNamesSomebody,
  toStageDefinition,
  toStageDraft,
  type StageDraft,
} from "@/modules/approvals/workflowStages";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import {
  targetTypeLabel,
  useOfferedTargetTypes,
} from "@/modules/approvals/targetTypes";

/**
 * The stage a new workflow starts with. Its label is a suggestion the user
 * edits, so it belongs in their language — it used to read "Manager Approval"
 * in all five.
 */
function emptyStages(t: TFunction): StageDraft[] {
  return [
    {
      order: 1,
      label: t("workflows.defaultStageLabel"),
      approver_user_ids: [],
      open: false,
    },
  ];
}

/**
 * Who decides a stage, for the workflow list: anyone with the grant for an
 * open stage, the people a stage names, or their count while the member list
 * is not there to name them from.
 */
function approverSummary(
  t: TFunction,
  memberNameById: Map<string, string>,
  stage: StageDefinition,
): string {
  const ids = stage.approver_user_ids ?? [];
  if (ids.length === 0) return t("workflows.decidersOpen");
  const names = ids
    .map((id) => memberNameById.get(id))
    .filter((name): name is string => Boolean(name));
  return names.length > 0
    ? names.join(", ")
    : t("dashboard.stepper.approversAssigned", { count: ids.length });
}

interface WorkflowCardProps {
  workflow: ApprovalWorkflow;
  canConfigure: boolean;
  approverSummary: (stage: StageDefinition) => string;
  onToggleActive: (wf: ApprovalWorkflow) => void;
  onEdit: (wf: ApprovalWorkflow) => void;
  onDelete: (wf: ApprovalWorkflow) => void;
}

function WorkflowCard({
  workflow: wf,
  canConfigure,
  approverSummary,
  onToggleActive,
  onEdit,
  onDelete,
}: WorkflowCardProps) {
  const { t } = useTranslation(["approvals", "common"]);
  return (
    /* No hover lift: the card goes nowhere. Its buttons are the only things
       on it that do anything, and a surface that rises under the pointer
       reads as a surface that can be pressed. */
    <Card>
      <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <p className="font-medium text-on">{wf.name}</p>
            <span
              className={cn(
                "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
                wf.is_active
                  ? "bg-success-50 text-success-700"
                  : "bg-surface-inset text-on-muted",
              )}
            >
              {wf.is_active ? t("workflows.active") : t("workflows.inactive")}
            </span>
          </div>
          <p className="text-xs text-on-muted">
            {t("workflows.summary", {
              target: targetTypeLabel(t, wf.target_type),
              count: wf.stages.length,
            })}
          </p>
          <div className="mt-2 flex flex-col gap-1">
            {wf.stages.map((s) => (
              <div
                key={s.order}
                className="flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5 text-xs"
              >
                <span className="font-medium text-on-secondary">
                  {s.order}. {s.label}
                </span>
                <span className="text-on-muted">· {approverSummary(s)}</span>
              </div>
            ))}
          </div>
          <WorkflowScopeLine workflow={wf} />
          <WorkflowRequestersLine workflow={wf} />
          {/* The verdict travels with every row; the notice stands under the
              stages it judges, next to the Edit button that fixes it. */}
          <ApprovalDeadEndNotice
            subject={wf}
            waiting={wf.waiting_requests}
            title={t("workflows.deadEndTitle")}
            className="mt-2"
          />
        </div>
        {canConfigure && (
          /* One weight for every action: a boxed Edit between two bare red
             labels stood at three weights and read as a misaligned row. The
             colour says what switches off or removes (§2.13a) — Deactivate
             only while the workflow is on — and the divider fences off the
             one action that cannot be taken back. */
          <div
            data-testid={`workflow-actions-${wf.id}`}
            className="flex shrink-0 items-center gap-1 self-end sm:self-auto"
          >
            <Button
              variant="ghost"
              size="sm"
              leftIcon={<Pencil size={14} />}
              onClick={() => onEdit(wf)}
            >
              {t("common:actions.edit")}
            </Button>
            <Button
              variant={wf.is_active ? "ghostDanger" : "ghost"}
              size="sm"
              leftIcon={<Power size={14} />}
              onClick={() => onToggleActive(wf)}
            >
              {wf.is_active
                ? t("workflows.deactivate")
                : t("workflows.activate")}
            </Button>
            <span
              aria-hidden="true"
              className="w-px h-5 shrink-0 bg-border mx-1"
            />
            <Button
              variant="ghostDanger"
              size="sm"
              leftIcon={<Trash2 size={14} />}
              onClick={() => onDelete(wf)}
            >
              {t("common:actions.delete")}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

interface WorkflowFormCardProps {
  editing: boolean;
  targetType: string;
  name: string;
  stages: StageDraft[];
  requesterScope: RequesterScope | null;
  isSaving: boolean;
  onTargetTypeChange: (value: string) => void;
  onNameChange: (value: string) => void;
  onRequesterScopeChange: (scope: RequesterScope) => void;
  onStagesChange: (stages: StageDraft[]) => void;
  onSubmit: (e?: FormEvent) => void;
  onCancel: () => void;
}

/**
 * The create/edit form for one workflow.
 *
 * Split out of the page for the same reason the stage editor exists: the page
 * owns the list, the form owns the draft — and a form that outgrows the page
 * makes the page unreadable (see the ESLint function-length guard).
 */
function WorkflowFormCard({
  editing,
  targetType,
  name,
  stages,
  requesterScope,
  isSaving,
  onTargetTypeChange,
  onNameChange,
  onRequesterScopeChange,
  onStagesChange,
  onSubmit,
  onCancel,
}: WorkflowFormCardProps) {
  const { t } = useTranslation(["approvals", "common"]);
  const offeredTargets = useOfferedTargetTypes();
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {editing ? t("workflows.edit") : t("workflows.create")}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="space-y-4">
          {!editing && offeredTargets.length > 0 && (
            <Select
              label={t("workflows.targetType")}
              value={targetType}
              onChange={onTargetTypeChange}
              options={offeredTargets.map((id) => ({
                id,
                name: t(`workflows.targetType_${id}`),
              }))}
            />
          )}
          {/* Nothing switched on raises requests: there is no target to
              pick, and the form says so instead of saving one it hides. */}
          {!editing && offeredTargets.length === 0 && (
            <p role="status" className="text-sm text-on-secondary">
              {t("workflows.noTargetTypes")}
            </p>
          )}
          <Input
            data-testid="workflow-name-input"
            label={t("workflows.name")}
            placeholder={t("workflows.namePlaceholder")}
            value={name}
            onChange={(e) => onNameChange(e.target.value)}
            aria-required
            // An edit opens with the name filled in, so an empty one was
            // cleared on purpose and the disabled button beside it needs a
            // reason on screen. A new workflow starts empty and says nothing
            // until it has been typed into.
            error={
              editing && !name.trim() ? t("workflows.nameRequired") : undefined
            }
          />
          <RequesterScopeField
            value={requesterScope}
            onChange={onRequesterScopeChange}
          />
          {/* What a workflow is: the *who* of approval. It stands in for a
              silent document profile — meaning every confirmed document —
              while a configured threshold or type list stays the filter, so
              the form says which before the stages are written. Worn like the
              page's own tip above the list: a grey inset fill read as a
              disabled field rather than a note. */}
          {targetType === "document" && (
            <p
              data-testid="workflow-gates-documents"
              className="flex items-start gap-2 rounded-lg border border-primary-200 bg-primary-50/50 p-3 text-xs text-on-secondary"
            >
              <Info size={14} className="mt-0.5 shrink-0 text-primary-700" />
              <span>{t("workflows.gatesDocuments")}</span>
            </p>
          )}
          {!editing && (
            <p className="text-xs text-on-muted">{t("workflows.savedOff")}</p>
          )}
          <ApprovalWorkflowEditor stages={stages} onChange={onStagesChange} />
          <div className="flex items-center justify-end gap-2">
            <Button type="button" variant="outline" onClick={onCancel}>
              {t("common:actions.cancel")}
            </Button>
            <Button
              data-testid="workflow-submit-btn"
              variant="primary"
              type="submit"
              isLoading={isSaving}
              disabled={
                (!editing && !offeredTargets.includes(targetType)) ||
                !name.trim() ||
                stages.length === 0 ||
                !stages.every(stageNamesSomebody) ||
                !requesterScopeNamesSomebody(requesterScope)
              }
            >
              {editing ? t("workflows.saveChanges") : t("workflows.create")}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

/** Who the stages name, by id; `membersError` is set when that list failed. */
function useMemberNames() {
  const membersQuery = useOrgMembers();
  const members = membersQuery.data;
  const memberNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const m of members ?? []) map.set(m.id, m.full_name ?? m.email);
    return map;
  }, [members]);
  return {
    memberNameById,
    membersError: membersQuery.isError ? membersQuery.error : null,
    retryMembers: () => void membersQuery.refetch(),
  };
}

/**
 * A warning that says no workflow exists sends the reader here with "?new=1"
 * (and "&target=" for the kind it is about) — the form opens on arrival
 * instead of asking them to find the button they were just promised. A
 * reader who may not configure only has the link consumed.
 */
function useOpenCreateFromLink(
  canConfigure: boolean,
  resetForm: () => void,
  setTargetType: (target: string) => void,
  setShowCreate: (open: boolean) => void,
) {
  const [searchParams, setSearchParams] = useSearchParams();
  const offeredTargets = useOfferedTargetTypes();
  useEffect(() => {
    if (searchParams.get("new") !== "1") return;
    if (canConfigure) {
      const target = searchParams.get("target") ?? "";
      resetForm();
      if (offeredTargets.includes(target)) {
        setTargetType(target);
      }
      setShowCreate(true);
    }
    const next = new URLSearchParams(searchParams);
    next.delete("new");
    next.delete("target");
    setSearchParams(next, { replace: true });
  }, [
    searchParams,
    setSearchParams,
    offeredTargets,
    canConfigure,
    resetForm,
    setTargetType,
    setShowCreate,
  ]);
}

export default function WorkflowSettingsPage() {
  const { t } = useTranslation(["approvals", "common"]);
  const { setHeader } = useModulePageHeader();
  const {
    data: workflows,
    isLoading,
    isError,
    error,
    refetch,
  } = useApprovalWorkflows();
  // Listing the workflows is answered to approvals:read (configuring
  // implies it) — a role holding neither gets a filtered 200, an empty
  // list that is a boundary, not a report about the organization. The
  // page says which of the two it is instead of borrowing the other's
  // empty state.
  const canRead = useCanReadWorkflows();
  const canConfigure = useCanConfigureWorkflows();
  const createWorkflow = useCreateWorkflow();
  const updateWorkflow = useUpdateWorkflow();
  const deleteWorkflow = useDeleteWorkflow();
  const navigate = useNavigate();
  const { memberNameById, membersError, retryMembers } = useMemberNames();

  const stageApproverSummary = (stage: StageDefinition) =>
    approverSummary(t, memberNameById, stage);

  const [showCreate, setShowCreate] = useState(false);
  // The workflow the admin is about to switch off, and how. Both ways ask
  // first: what waits on it is released, and the dialog says how many.
  const [switchOff, setSwitchOff] = useState<{
    workflow: ApprovalWorkflow;
    mode: SwitchOffMode;
  } | null>(null);
  // Switching on goes through a dialog that says what the workflow will hold.
  const [activationTarget, setActivationTarget] =
    useState<ApprovalWorkflow | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);

  // Only what a switched-on module can raise is offered; the first of those
  // is where a new workflow starts — none, when nothing is offered.
  const firstTarget = useOfferedTargetTypes()[0] ?? "";
  const [formTargetType, setFormTargetType] = useState(firstTarget);
  const [formName, setFormName] = useState("");
  const [formStages, setFormStages] = useState<StageDraft[]>(() =>
    emptyStages(t),
  );
  // No default: whose submissions a workflow holds is chosen, never implied.
  const [formRequesters, setFormRequesters] = useState<RequesterScope | null>(
    null,
  );
  const [isSaving, setIsSaving] = useState(false);
  // The refusal the server sends for a stage nobody could decide, held until
  // the user says they mean it.
  const [consentPrompt, setConsentPrompt] = useState<{
    message: string;
  } | null>(null);

  // A workflow is a name, a target type and a list of stages, each with a
  // label and its approvers — a dozen fields typed by hand, on the page
  // rather than in a dialog, so a click on a module tab takes the route and
  // the draft with it. That is the class `formGuardStore` was written for;
  // this form was simply never wired to it. The snapshot is taken when the
  // form opens, so the values the edit button seeds are not the reader's
  // work and asking about them would teach the reader to click through.
  const formDraft = useMemo(
    () =>
      JSON.stringify({ formTargetType, formName, formStages, formRequesters }),
    [formTargetType, formName, formStages, formRequesters],
  );
  const [openedDraft, setOpenedDraft] = useState<string | null>(null);
  useEffect(() => {
    if (!showCreate) {
      setOpenedDraft(null);
      return;
    }
    setOpenedDraft((prev) => prev ?? formDraft);
  }, [showCreate, formDraft]);
  useFormGuard(
    showCreate && openedDraft !== null && openedDraft !== formDraft,
    t("approvals:workflows.guardName"),
  );

  // Memoised because the header effect calls it, and it now depends on `t`
  // (the first stage's label is translated).
  const resetForm = useCallback(() => {
    setFormTargetType(firstTarget);
    setFormName("");
    setFormStages(emptyStages(t));
    setFormRequesters(null);
    setShowCreate(false);
    setEditingId(null);
  }, [t, firstTarget]);

  useOpenCreateFromLink(
    canConfigure,
    resetForm,
    setFormTargetType,
    setShowCreate,
  );

  useEffect(() => {
    setHeader({
      title: t("approvals:workflows.title"),
      subtitle: t("approvals:workflows.subtitle"),
      actions: canConfigure ? (
        <Button
          variant="primary"
          leftIcon={<Plus size={16} />}
          onClick={() => {
            resetForm();
            setShowCreate(true);
          }}
        >
          {t("approvals:workflows.create")}
        </Button>
      ) : undefined,
    });
  }, [t, setHeader, canConfigure, resetForm]);

  const handleSave = async (e?: FormEvent, allowUndecidable = false) => {
    e?.preventDefault();
    if (!formName.trim()) {
      toast.warning(t("workflows.nameRequired"));
      return;
    }
    if (!requesterScopeNamesSomebody(formRequesters)) return;
    if (!formStages.every(stageNamesSomebody)) return;
    const stages = formStages.map(toStageDefinition);
    setIsSaving(true);
    try {
      if (editingId) {
        await updateWorkflow.mutateAsync({
          id: editingId,
          data: {
            name: formName,
            stages,
            requester_scope: formRequesters,
            ...(allowUndecidable ? { allow_undecidable_stages: true } : {}),
          },
        });
        toast.success(t("workflows.updated"));
      } else {
        await createWorkflow.mutateAsync({
          // The contract types the target as a closed union; the picker only offers its members.
          target_type: formTargetType as WorkflowCreateInput["target_type"],
          name: formName,
          stages,
          requester_scope: formRequesters,
          ...(allowUndecidable ? { allow_undecidable_stages: true } : {}),
        });
        toast.success(t("workflows.created"));
      }
      resetForm();
    } catch (err: unknown) {
      const message = extractApiError(err, t("workflows.saveFailed"));
      // A stage nobody could decide is refused with a way past it: the
      // dialog names the stage the server objected to, and saving again
      // carries the consent flag. The code decides, not the sentence — the
      // sentence is translated, this is not.
      if (
        !allowUndecidable &&
        extractApiErrorCode(err) === STAGE_UNSOLVABLE_CODE
      ) {
        setConsentPrompt({ message });
        return;
      }
      if (message.includes("duplicate")) {
        toast.error(t("workflows.duplicateTarget"));
      } else {
        toast.error(message);
      }
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async (wf: ApprovalWorkflow) => {
    const outcome = await deleteWorkflow.mutateAsync(wf.id);
    // The record is gone either way; an editor still open on it could only
    // save into "not found". Another workflow's draft is left alone.
    if (editingId === wf.id) resetForm();
    if (!outcome.archived) {
      toast.success(t("workflows.deleted"));
      return;
    }
    // The workflow leaves the list either way; what the reader still has to
    // be told is where its requests went, and the way there — the dashboard
    // opens on what is open, and these are all closed.
    toast.success(t("workflows.archived", { count: outcome.requests_kept }), {
      action: {
        label: t("workflows.archivedShow"),
        onClick: () => navigate("/approvals?status="),
      },
    });
  };

  const handleDeactivate = async (wf: ApprovalWorkflow) => {
    await updateWorkflow.mutateAsync({ id: wf.id, data: { is_active: false } });
    toast.success(t("workflows.deactivated"));
  };

  // A rejection keeps the dialog open with the reason inside it (the
  // ConfirmDialog contract), so the toast the old handlers raised is gone.
  const confirmSwitchOff = async () => {
    if (!switchOff) return;
    if (switchOff.mode === "delete") await handleDelete(switchOff.workflow);
    else await handleDeactivate(switchOff.workflow);
    setSwitchOff(null);
  };

  const startEdit = (wf: ApprovalWorkflow) => {
    setEditingId(wf.id);
    setFormTargetType(wf.target_type);
    setFormName(wf.name);
    setFormStages(wf.stages.map(toStageDraft));
    setFormRequesters(wf.requester_scope);
    setShowCreate(true);
  };

  // Both directions ask first: off says what waits and is released, on says
  // what the workflow will hold.
  const handleToggleActive = (wf: ApprovalWorkflow) => {
    if (wf.is_active) setSwitchOff({ workflow: wf, mode: "deactivate" });
    else setActivationTarget(wf);
  };

  return (
    <div className="space-y-6">
      {/* The two empty states below already say which boundary the reader is
          against. A list that is not empty said nothing, so a reader saw
          cards with no actions on them and no reason given. */}
      {canRead && (
        <ReadOnlyNotice module="approvals" permission="approvals:configure" />
      )}
      {workflows && workflows.length > 0 && (
        <div className="flex items-start gap-2 rounded-lg border border-primary-200 bg-primary-50/50 p-3 text-xs text-on-secondary">
          <Info size={14} className="mt-0.5 shrink-0 text-primary-700" />
          <span>{t("workflows.selfApproveBanner")}</span>
        </div>
      )}
      {/* Without the members every stage falls back to its role, which reads
          as the answer to "who approves". */}
      {membersError != null && (
        <InlineQueryError error={membersError} onRetry={retryMembers} />
      )}
      {isError ? (
        <QueryFailure error={error} onRetry={() => refetch()} />
      ) : isLoading ? (
        <div className="flex items-center justify-center py-12">
          <p className="text-on-muted">{t("common:messages.loading")}</p>
        </div>
      ) : !canRead ? (
        // The server filters this list, so for this account it is empty
        // whatever the organization has configured — a permission line,
        // not a report of "nothing configured yet".
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <DynamicIcon
            name="Lock"
            size={48}
            className="text-on-muted/40 mb-4"
          />
          <h3 className="text-lg font-medium text-on">
            {t("workflows.emptyNoRead")}
          </h3>
          <p className="mt-1 max-w-md text-sm text-on-muted">
            {t("workflows.emptyNoReadHint")}
          </p>
        </div>
      ) : !workflows?.length && !showCreate ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <DynamicIcon
            name="CheckCheck"
            size={48}
            className="text-on-muted/40 mb-4"
          />
          <h3 className="text-lg font-medium text-on">
            {t("workflows.empty")}
          </h3>
          <p className="mt-1 max-w-md text-sm text-on-muted">
            {canConfigure
              ? t("workflows.emptyHint")
              : t("workflows.emptyHintReadOnly")}
          </p>
          {canConfigure && (
            <Button
              // Outline, not primary: the header already carries the view's
              // one filled create, and this is the same action a second
              // time. The entry stays because the empty state is where a
              // first-time reader is looking.
              variant="outline"
              className="mt-4"
              leftIcon={<Plus size={16} />}
              onClick={() => {
                resetForm();
                setShowCreate(true);
              }}
            >
              {t("workflows.create")}
            </Button>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {workflows?.map((wf) => (
            <WorkflowCard
              key={wf.id}
              workflow={wf}
              canConfigure={canConfigure}
              approverSummary={stageApproverSummary}
              onToggleActive={handleToggleActive}
              onEdit={startEdit}
              onDelete={(wf) => setSwitchOff({ workflow: wf, mode: "delete" })}
            />
          ))}
        </div>
      )}

      {showCreate && (
        <WorkflowFormCard
          editing={!!editingId}
          targetType={formTargetType}
          name={formName}
          stages={formStages}
          requesterScope={formRequesters}
          isSaving={isSaving}
          onTargetTypeChange={setFormTargetType}
          onNameChange={setFormName}
          onRequesterScopeChange={setFormRequesters}
          onStagesChange={setFormStages}
          onSubmit={handleSave}
          onCancel={resetForm}
        />
      )}

      <WorkflowSwitchOffDialog
        workflow={switchOff?.workflow ?? null}
        mode={switchOff?.mode ?? "deactivate"}
        onConfirm={confirmSwitchOff}
        onCancel={() => setSwitchOff(null)}
      />

      <WorkflowActivationDialog
        workflow={activationTarget}
        onClose={() => setActivationTarget(null)}
      />

      {/* The server refused a stage nobody could decide. Saving it anyway is
          allowed, deliberately, and this is where that consent is given. */}
      <ConfirmDialog
        open={!!consentPrompt}
        title={t("workflows.undecidableTitle")}
        message={`${consentPrompt?.message ?? ""} ${t("workflows.undecidableHint")}`}
        confirmLabel={t("workflows.undecidableSave")}
        onConfirm={() => {
          setConsentPrompt(null);
          void handleSave(undefined, true);
        }}
        onCancel={() => setConsentPrompt(null)}
      />
    </div>
  );
}
