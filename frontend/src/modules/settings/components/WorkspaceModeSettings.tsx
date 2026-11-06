import { useState, useMemo, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, ArrowRight, Check } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { QueryFailure } from "@/components/ui/QueryResult";
import { cn } from "@/lib/utils";
import {
  useProfiles,
  useProfileSwitchApply,
  useProfileSwitchPreview,
} from "@/modules/onboarding/moduleApi";
import { useOrganization } from "@/modules/settings/hooks/useOrganization";
import { useModuleLabels } from "@/hooks/useModuleLabels";
import { useAvailableModules } from "@/modules/settings/hooks/useModules";
import { useProfileLabels } from "@/modules/settings/hooks/useProfileLabels";
import type { ProductProfile, ProfileSwitchDiff } from "@/types";

/**
 * WorkspaceModeSettings — admin-only UI to switch the active product profile.
 *
 * Flow:
 *   1. User picks a different profile from the radio list → the preview
 *      (POST /switch-profile with dry_run=true) fires automatically and the
 *      diff renders as soon as it loads.
 *   2. User clicks "Apply" → a ConfirmDialog summarises the modules being
 *      disabled → confirm issues POST /switch-profile with dry_run=false.
 *   3. The active profile's card carries "Apply again" — a re-apply, not a
 *      switch. Nothing enables or disables; the profile's setup runs again
 *      in this session's language, which is the one move that reaches names
 *      seeded by profiles the organization left behind (a checked radio
 *      cannot be re-picked, so the path is a button, not the radio).
 *
 * The active profile is highlighted and disabled in the list. Module ids in
 * the diff are rendered with their catalog display names when available.
 *
 * Every profile label on this screen — card, radio aria-label, "Target: …",
 * the diff subtitle and the confirm title — goes through `useProfileLabels`,
 * so a Polish user never reads the registry's English (docs/MODULE_NAMES.md
 * § "Workspace mode names").
 */
export function WorkspaceModeSettings() {
  const { t } = useTranslation(["launcher", "common"]);
  const {
    data: profiles,
    isLoading: loadingProfiles,
    isError: profilesFailed,
    error: profilesError,
    refetch: refetchProfiles,
  } = useProfiles();
  const { data: org } = useOrganization();
  const previewMutation = useProfileSwitchPreview();
  const applyMutation = useProfileSwitchApply();
  const moduleLabels = useModuleLabels();
  const { data: moduleCatalogue } = useAvailableModules();
  const profileLabels = useProfileLabels();
  /**
   * Name a module the way the rest of the app names it, and say nothing about
   * the ones this screen has no business naming.
   *
   * The diff used to render `display_name` straight from the manifest — English
   * in a Polish interface (`Approvals`, `Purchase Orders`) — and, for shell
   * modules with no manifest at all, the bare identifier (`categories`,
   * `core`). Those four are always on, so listing them as part of a profile
   * switch was noise on top of being unreadable: they are dropped, and the
   * rest goes through `modules.<name>.name` (docs/MODULE_NAMES.md).
   */
  const describeModule = useCallback(
    (id: string): string | null => {
      const entry = moduleCatalogue?.find((mod) => mod.name === id);
      if (!entry) return null;
      return moduleLabels(entry).name;
    },
    [moduleCatalogue, moduleLabels],
  );

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [diff, setDiff] = useState<ProfileSwitchDiff | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [reapplyOpen, setReapplyOpen] = useState(false);

  const activeId = org?.active_profile_id ?? null;

  const selectedProfile: ProductProfile | null = useMemo(() => {
    if (!selectedId || !profiles) return null;
    return profiles.find((p) => p.id === selectedId) ?? null;
  }, [selectedId, profiles]);

  const profileNames = useMemo(
    () => new Map((profiles ?? []).map((p) => [p.id, profileLabels(p).name])),
    [profiles, profileLabels],
  );
  const profileLabel = (id: string | null) =>
    id ? (profileNames.get(id) ?? id) : "—";

  const sameAsActive = !selectedId || selectedId === activeId;
  const isMutating = previewMutation.isPending || applyMutation.isPending;
  const hasDisables =
    !!diff && diff.disable.length + diff.cascade_disable.length > 0;

  function handleSelect(profileId: string) {
    setSelectedId(profileId);
    setDiff(null);
    previewMutation.mutate(profileId, {
      onSuccess: (result) => setDiff(result.diff),
    });
  }

  async function handleConfirmApply() {
    if (!selectedId) return;
    await applyMutation.mutateAsync(selectedId);
    setConfirmOpen(false);
    setDiff(null);
    setSelectedId(null);
  }

  async function handleConfirmReapply() {
    if (!activeId) return;
    await applyMutation.mutateAsync(activeId);
    setReapplyOpen(false);
  }

  if (loadingProfiles) {
    return (
      <Card className="p-6">
        <div className="flex items-center gap-2 text-on-muted">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span>{t("launcher:workspace.loading")}</span>
        </div>
      </Card>
    );
  }

  // "No workspace modes available." describes the installation. It is the wrong
  // thing to tell an administrator who came here to change how the workspace
  // works and whose list simply did not arrive.
  if (profilesFailed) {
    return (
      <Card className="p-6">
        <QueryFailure error={profilesError} onRetry={() => refetchProfiles()} />
      </Card>
    );
  }

  if (!profiles || profiles.length === 0) {
    return (
      <Card className="p-6">
        <p className="text-sm text-on-muted">{t("launcher:workspace.empty")}</p>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <Card className="p-6">
        {/* Two cards share the page now, so this one names itself. The page's
            subtitle is the shell header's, 40px above. */}
        <h2 className="text-base font-semibold text-on">
          {t("common:settings.myModules.setTitle")}
        </h2>
        <p className="mt-1 text-sm text-on-muted">
          {t("common:settings.myModules.setHint")}
        </p>

        <ul role="radiogroup" className="mt-4 space-y-2">
          {profiles.map((profile) => {
            const isActive = profile.id === activeId;
            const isSelected = profile.id === selectedId;
            // The radio group always has a checked value: the explicit pick,
            // or the active profile when nothing was picked yet.
            const isChecked = profile.id === (selectedId ?? activeId);
            const labels = profileLabels(profile);
            return (
              <li
                key={profile.id}
                className={cn(
                  "relative rounded-xl border transition-colors",
                  isSelected
                    ? "border-primary-500 bg-primary-50/40 dark:bg-primary-950/20"
                    : "border-border hover:bg-surface-raised",
                  isActive && "ring-1 ring-accent-300",
                )}
              >
                <label
                  className={cn(
                    "flex items-start gap-3 p-3 cursor-pointer",
                    // From md up the active card carries the re-apply button
                    // on its right edge, and the text keeps its width so it
                    // wraps instead of running under the button. Below md the
                    // button gets its own row under the text, so the text
                    // keeps the card's full width.
                    isActive && "md:pr-40",
                  )}
                >
                  <input
                    type="radio"
                    name="workspace-mode"
                    value={profile.id}
                    checked={isChecked}
                    onChange={() => handleSelect(profile.id)}
                    className="mt-1 h-4 w-4 text-primary-600 focus:ring-primary-500"
                    aria-label={labels.name}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold text-on">
                        {labels.name}
                      </span>
                      {isActive && (
                        <span className="inline-flex items-center gap-1 text-[10px] font-medium uppercase tracking-wider text-accent-700 bg-accent-50 rounded-md px-1.5 py-0.5">
                          <Check size={10} strokeWidth={3} />
                          {t("launcher:workspace.current")}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-on-muted mt-0.5">
                      {labels.description}
                    </p>
                  </div>
                </label>
                {/*
                  Re-applying the current profile has no radio to click — it
                  is already checked, and a second click on a checked radio
                  fires nothing. The button sits outside the label (a click
                  inside a label belongs to the radio), and says what it does
                  before the dialog repeats it: the setup runs again, so
                  names the profile once seeded — storage types included —
                  are rewritten in this session's language. That is the one
                  move that reaches rows profiles the organization left
                  behind.
                */}
                {isActive && (
                  <div className="pb-3 pl-10 pr-3 md:absolute md:right-3 md:top-3 md:p-0">
                    <Button
                      type="button"
                      variant="secondary"
                      className="w-full md:w-auto"
                      onClick={() => setReapplyOpen(true)}
                      disabled={isMutating}
                      data-testid="workspace-reapply-button"
                      title={t("launcher:workspace.reapplyHint")}
                    >
                      {t("launcher:workspace.reapply")}
                    </Button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="primary"
            onClick={() => setConfirmOpen(true)}
            disabled={!selectedId || sameAsActive || !diff || isMutating}
            data-testid="workspace-apply-button"
          >
            {applyMutation.isPending && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}
            {t("launcher:workspace.apply")}
            <ArrowRight size={16} />
          </Button>
          {!sameAsActive && selectedProfile && (
            <span className="text-xs text-on-muted">
              {t("launcher:workspace.target", {
                name: profileLabels(selectedProfile).name,
              })}
            </span>
          )}
        </div>
      </Card>

      {previewMutation.isPending && (
        <div
          className="h-24 animate-pulse rounded-xl bg-surface-raised"
          role="status"
          aria-label={t("launcher:workspace.previewLoading")}
        />
      )}

      {diff && (
        <DiffCard
          diff={diff}
          profileLabel={profileLabel}
          describeModule={describeModule}
        />
      )}

      <ConfirmDialog
        open={confirmOpen}
        title={t("launcher:workspace.confirmTitle", {
          name: selectedProfile ? profileLabels(selectedProfile).name : "",
        })}
        message={t("launcher:workspace.confirmMessage")}
        confirmLabel={t("launcher:workspace.confirmApply")}
        cancelLabel={t("common:actions.cancel")}
        variant={hasDisables ? "warning" : "default"}
        onConfirm={handleConfirmApply}
        onCancel={() => setConfirmOpen(false)}
      >
        {diff && (
          <>
            <DiffRow
              label={t("launcher:workspace.diffDisable")}
              items={diff.disable}
              variant="remove"
              describe={describeModule}
            />
            {diff.cascade_disable.length > 0 && (
              <DiffRow
                label={t("launcher:workspace.diffCascade")}
                items={diff.cascade_disable}
                variant="cascade"
                describe={describeModule}
                hint={t("launcher:workspace.diffCascadeHint")}
              />
            )}
          </>
        )}
      </ConfirmDialog>

      <ConfirmDialog
        open={reapplyOpen}
        title={t("launcher:workspace.confirmReapplyTitle", {
          name: profileLabel(activeId),
        })}
        message={t("launcher:workspace.confirmReapplyMessage")}
        confirmLabel={t("launcher:workspace.confirmReapply")}
        cancelLabel={t("common:actions.cancel")}
        variant="default"
        onConfirm={handleConfirmReapply}
        onCancel={() => setReapplyOpen(false)}
      />
    </div>
  );
}

/** What a profile switch would change, read before it is applied. */
function DiffCard({
  diff,
  profileLabel,
  describeModule,
}: {
  diff: ProfileSwitchDiff;
  profileLabel: (id: string | null) => string;
  describeModule: (id: string) => string | null;
}) {
  const { t } = useTranslation(["launcher"]);
  return (
    <Card className="p-6" data-testid="workspace-diff">
      <h3 className="text-sm font-semibold text-on">
        {t("launcher:workspace.diffTitle")}
      </h3>
      <p className="text-xs text-on-muted mt-0.5">
        {t("launcher:workspace.diffSubtitle", {
          from: profileLabel(diff.from_profile_id),
          to: profileLabel(diff.to_profile_id),
        })}
      </p>
      <dl className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
        <DiffRow
          label={t("launcher:workspace.diffEnable")}
          items={diff.enable}
          variant="add"
          describe={describeModule}
        />
        <DiffRow
          label={t("launcher:workspace.diffDisable")}
          items={diff.disable}
          variant="remove"
          describe={describeModule}
        />
        {diff.cascade_disable.length > 0 && (
          <DiffRow
            label={t("launcher:workspace.diffCascade")}
            items={diff.cascade_disable}
            variant="cascade"
            describe={describeModule}
            hint={t("launcher:workspace.diffCascadeHint")}
          />
        )}
        <DiffRow
          label={t("launcher:workspace.diffUnchanged")}
          items={diff.unchanged}
          variant="neutral"
          describe={describeModule}
        />
        <DiffRow
          label={t("launcher:workspace.diffManualKept")}
          items={diff.manual_kept}
          variant="neutral"
          describe={describeModule}
        />
        {diff.module_config_overwrite.length > 0 && (
          <DiffRow
            label={t("launcher:workspace.diffConfig")}
            items={diff.module_config_overwrite}
            variant="neutral"
            describe={describeModule}
            hint={t("launcher:workspace.diffConfigHint")}
          />
        )}
      </dl>
      {diff.offer_location_renumbering && (
        <p
          className="mt-4 rounded-lg bg-surface-raised px-3 py-2 text-sm text-on-secondary"
          data-testid="workspace-renumber-offer"
        >
          {t("launcher:workspace.renumberOffer")}
        </p>
      )}
    </Card>
  );
}

interface DiffRowProps {
  label: string;
  items: string[];
  variant: "add" | "remove" | "cascade" | "neutral";
  /** Module id → user-visible name, or null when it should not be listed. */
  describe: (id: string) => string | null;
  hint?: string;
}

function DiffRow({ label, items, variant, describe, hint }: DiffRowProps) {
  const named = items
    .map((item) => ({ id: item, name: describe(item) }))
    .filter(
      (entry): entry is { id: string; name: string } => entry.name !== null,
    );
  if (named.length === 0) return null;
  const colour =
    variant === "add"
      ? "text-accent-700 bg-accent-50"
      : variant === "remove"
        ? "text-rose-700 bg-rose-50"
        : variant === "cascade"
          ? "text-amber-700 bg-amber-50"
          : "text-on-secondary bg-surface-raised";
  return (
    <div>
      <dt className="text-xs font-medium text-on-muted">{label}</dt>
      {hint && <p className="text-xs text-on-muted mt-0.5">{hint}</p>}
      <dd className="mt-1 flex flex-wrap gap-1">
        {named.map((entry) => (
          <span
            key={entry.id}
            className={cn(
              "inline-flex items-center text-xs font-medium rounded-md px-2 py-0.5",
              colour,
            )}
          >
            {entry.name}
          </span>
        ))}
      </dd>
    </div>
  );
}
