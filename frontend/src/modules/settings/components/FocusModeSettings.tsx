import { useState, useMemo, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Loader2, ArrowRight } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { QueryFailure } from "@/components/ui/QueryResult";
import { cn } from "@/lib/utils";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { STANDALONE_MODULE_NAMES } from "@/lib/moduleRegistry/standaloneModuleNames";
import { useModuleLabels } from "@/hooks/useModuleLabels";
import {
  useAvailableModules,
  useMyModules,
  useFocusModule,
  useFocusModePreview,
  useFocusModeApply,
  useFocusModeExit,
} from "@/modules/settings/hooks/useModules";
import type { ModuleInfo } from "@/types";
import type { FocusModeDiff } from "@/lib/api/modules";

/**
 * FocusModeSettings — the "Show only <module>" toggles on the My modules page.
 *
 * Each module that can be shown on its own gets one toggle worded "Show only
 * <name>". Turning one on fires the preview (POST /modules/focus/preview) and
 * asks for confirmation with the change in front of the reader — showing one
 * module switches the others off for the whole organization — before POSTing
 * /modules/focus. Turning the toggle off asks the same way and DELETEs
 * /modules/focus, which puts every module back.
 *
 * The toggle shows the choice being asked about, not a saved state: while the
 * preview runs or the question is open, the pending module reads as on and the
 * previously focused one as off, and a cancelled question puts things back.
 * A failed question puts things back too — its choice survives only as the
 * retry button's target, so a choice that was never saved cannot read as the
 * saved on/off state.
 *
 * Only modules that declared `standalone` in their manifest are listed
 * (`moduleRegistry.getStandaloneModules`) — a module that never declared it
 * cannot be shown on its own, whatever the organization asks for.
 */
export function FocusModeSettings() {
  const { t, i18n } = useTranslation("common");
  const modulesQuery = useMyModules();
  const focusQuery = useFocusModule();
  const previewMutation = useFocusModePreview();
  const applyMutation = useFocusModeApply();
  const exitMutation = useFocusModeExit();
  const moduleLabels = useModuleLabels();
  const { data: moduleCatalogue } = useAvailableModules();

  // Same idiom as WorkspaceModeSettings: module ids are named through the
  // catalogue + `modules.<name>.name`, never from raw manifest English.
  const describeModule = useCallback(
    (id: string): string | null => {
      // The names live in the i18n bundle; the catalogue only supplies the
      // fallback for community modules, so a failed catalogue read still
      // leaves a module its label.
      const entry = moduleCatalogue?.find((mod) => mod.name === id) ?? {
        name: id,
        display_name: id,
        description: "",
      };
      return moduleLabels(entry).name;
    },
    [moduleCatalogue, moduleLabels],
  );

  /**
   * The module whose question is on the table — the one being previewed or
   * confirmed. `null` while nothing is being asked: the id is dropped when
   * the question is answered, cancelled, or dies with a failed preview, so
   * an uncommitted choice can never read as the saved on/off state. (While
   * one did, taking it back looked like leaving the focus — the DELETE
   * answers 409 with no focus, and deletes the real one when the failed
   * preview was a replacement of an existing focus.)
   */
  const [pendingId, setPendingId] = useState<string | null>(null);
  /**
   * The module whose preview failed — the retry button's target, remembered
   * by the mutation itself. It never drives the toggle.
   */
  const failedId = previewMutation.isError
    ? (previewMutation.variables ?? null)
    : null;
  const [diff, setDiff] = useState<FocusModeDiff | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [exitConfirmOpen, setExitConfirmOpen] = useState(false);

  const enabledModules = useMemo(
    () => modulesQuery.data ?? [],
    [modulesQuery.data],
  );
  const focusModule = focusQuery.focusModule;

  const standaloneModules = useMemo(
    () => moduleRegistry.getStandaloneModules(enabledModules),
    [enabledModules],
  );

  const pendingModule = useMemo(
    () => standaloneModules.find((mod) => mod.name === pendingId) ?? null,
    [standaloneModules, pendingId],
  );

  // Core labels the pending module overrides — the bundle for the current
  // interface language, English as fallback. Nothing renders for a module
  // that declares no overrides.
  const renameRows = useMemo(() => {
    const overrides = pendingModule?.i18nOverrides;
    if (!overrides) return [];
    const bundle = overrides[i18n.language] ?? overrides.en ?? {};
    return Object.entries(bundle).map(([key, next]) => ({
      key,
      current: t(key),
      next,
    }));
  }, [pendingModule, i18n.language, t]);

  const moduleName = useCallback(
    (id: string | null) => (id ? (describeModule(id) ?? id) : "—"),
    [describeModule],
  );

  const isBusy =
    previewMutation.isPending ||
    applyMutation.isPending ||
    exitMutation.isPending ||
    confirmOpen ||
    exitConfirmOpen;

  async function handleToggle(moduleId: string, on: boolean) {
    if (!on) {
      // "Off" means "stop showing just this module" only for the saved focus
      // — the one the organization is actually in. Any other module being
      // turned off is a choice that was never saved being taken back, and
      // there is nothing to ask: the exit would answer 409 with no focus, or
      // delete the focus a failed preview could not replace.
      if (moduleId !== focusModule) {
        setPendingId(null);
        setDiff(null);
        setConfirmOpen(false);
        return;
      }
      setExitConfirmOpen(true);
      return;
    }
    setPendingId(moduleId);
    setDiff(null);
    try {
      const result = await previewMutation.mutateAsync(moduleId);
      setDiff(result.diff ?? null);
      setConfirmOpen(true);
    } catch {
      // The question died with its preview and nothing was saved: the
      // choice steps out of the toggle. The failure is spoken for by the
      // notice below, and the mutation remembers the module for its retry.
      setPendingId(null);
    }
  }

  async function handleConfirmApply() {
    if (!pendingId) return;
    await applyMutation.mutateAsync(pendingId);
    setConfirmOpen(false);
    setDiff(null);
    setPendingId(null);
  }

  function handleCancelApply() {
    setConfirmOpen(false);
    setDiff(null);
    setPendingId(null);
  }

  async function handleConfirmShowAll() {
    await exitMutation.mutateAsync();
    setExitConfirmOpen(false);
  }

  if (modulesQuery.isLoading || focusQuery.isLoading) {
    return (
      <Card className="p-6">
        <h2 className="text-base font-semibold text-on">
          {t("settings.myModules.focusTitle")}
        </h2>
        <div className="mt-3 flex items-center gap-2 text-on-muted">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span>{t("settings.focus.loading")}</span>
        </div>
      </Card>
    );
  }

  if (modulesQuery.isError || focusQuery.isError) {
    return (
      <Card className="p-6">
        <h2 className="text-base font-semibold text-on">
          {t("settings.myModules.focusTitle")}
        </h2>
        <div className="mt-3">
          <QueryFailure
            error={modulesQuery.error ?? focusQuery.error}
            onRetry={() => {
              void modulesQuery.refetch();
              void focusQuery.refetch();
            }}
          />
        </div>
      </Card>
    );
  }

  const hasDisables = !!diff && diff.disable_all.length > 0;

  return (
    <div className="space-y-4">
      <Card className="p-6">
        <h2 className="text-base font-semibold text-on">
          {t("settings.myModules.focusTitle")}
        </h2>
        <p className="mt-1 text-sm text-on-muted">
          {t("settings.myModules.focusHint")}
        </p>

        {standaloneModules.length === 0 ? (
          <NothingToFocusOn
            catalogue={moduleCatalogue}
            enabledModules={enabledModules}
          />
        ) : (
          <ul className="mt-4 space-y-2">
            {standaloneModules.map((mod) => {
              const entry = moduleCatalogue?.find((m) => m.name === mod.name);
              const labels = moduleLabels(
                entry ?? {
                  name: mod.name,
                  display_name: mod.name,
                  description: "",
                },
              );
              return (
                <li
                  key={mod.name}
                  className={cn(
                    "rounded-xl border p-3 transition-colors",
                    mod.name === (pendingId ?? focusModule)
                      ? "border-primary-500 bg-primary-50/40 dark:bg-primary-950/20"
                      : "border-border",
                  )}
                >
                  <Checkbox
                    checked={mod.name === (pendingId ?? focusModule)}
                    disabled={isBusy}
                    onChange={(event) =>
                      handleToggle(mod.name, event.target.checked)
                    }
                    label={
                      <span className="text-sm font-medium text-on">
                        {t("settings.myModules.focusToggle", {
                          name: labels.name,
                        })}
                      </span>
                    }
                  />
                  {labels.description && (
                    <p className="mt-1 pl-6 text-xs text-on-muted">
                      {labels.description}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      {previewMutation.isPending && (
        <div
          className="h-24 animate-pulse rounded-xl bg-surface-raised"
          role="status"
          aria-label={t("settings.focus.previewLoading")}
        />
      )}

      {previewMutation.isError && failedId && (
        <Card className="p-4" role="alert" data-testid="focus-preview-failed">
          <p className="text-sm text-red-600 dark:text-red-400">
            {t("settings.focus.previewFailed")}
          </p>
          <Button
            type="button"
            variant="secondary"
            className="mt-2"
            onClick={() => handleToggle(failedId, true)}
          >
            {t("common:actions.retry")}
          </Button>
        </Card>
      )}

      <ConfirmDialog
        open={confirmOpen}
        title={t("settings.focus.confirmTitle", {
          name: pendingModule ? moduleName(pendingModule.name) : "",
        })}
        message={t("settings.focus.confirmMessage")}
        confirmLabel={t("settings.focus.confirmApply")}
        cancelLabel={t("common:actions.cancel")}
        variant={hasDisables ? "warning" : "default"}
        onConfirm={() => handleConfirmApply()}
        onCancel={handleCancelApply}
      >
        {diff && (
          <FocusDiffPreview
            diff={diff}
            renameRows={renameRows}
            describe={describeModule}
          />
        )}
      </ConfirmDialog>

      <ConfirmDialog
        open={exitConfirmOpen}
        title={t("settings.focus.showAllConfirmTitle")}
        message={t("settings.focus.showAllConfirmMessage")}
        confirmLabel={t("settings.focus.showAll")}
        cancelLabel={t("common:actions.cancel")}
        variant="default"
        onConfirm={() => handleConfirmShowAll()}
        onCancel={() => setExitConfirmOpen(false)}
      />
    </div>
  );
}

/**
 * No enabled module can run on its own. The sentence alone was a dead end, so
 * the screen names the modules that could, says none of them is on, and sends
 * the reader to the App Store — the one place that switches a module on, with
 * its warning about what the module would bring back — already searching for
 * that module.
 */
function NothingToFocusOn({
  catalogue,
  enabledModules,
}: {
  catalogue: ModuleInfo[] | undefined;
  enabledModules: string[];
}) {
  const { t } = useTranslation("common");
  const moduleLabels = useModuleLabels();
  // Only what this installation actually has: a module the backend does not
  // list cannot be switched on from anywhere.
  const candidates = STANDALONE_MODULE_NAMES.flatMap((name) => {
    const entry = catalogue?.find((m) => m.name === name);
    return entry ? [{ name, labels: moduleLabels(entry) }] : [];
  });
  return (
    <div className="mt-4 space-y-3" data-testid="focus-empty">
      <p className="text-sm text-on-muted">{t("settings.focus.empty")}</p>
      {candidates.length > 0 && (
        <>
          <p className="text-sm text-on-muted">
            {t("settings.focus.emptyHint")}
          </p>
          <ul className="space-y-2">
            {candidates.map(({ name, labels }) => {
              const on = enabledModules.includes(name);
              return (
                <li
                  key={name}
                  className="flex flex-wrap items-center gap-3 rounded-xl border border-border p-3"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-on">
                        {labels.name}
                      </span>
                      <span className="inline-flex items-center text-[10px] font-medium uppercase tracking-wider text-on-secondary bg-surface-raised rounded-md px-1.5 py-0.5">
                        {on
                          ? t("settings.focus.stateEnabled")
                          : t("settings.focus.stateNotEnabled")}
                      </span>
                    </div>
                    {labels.description && (
                      <p className="text-xs text-on-muted mt-0.5">
                        {labels.description}
                      </p>
                    )}
                  </div>
                  <Link
                    to={`/apps?module=${encodeURIComponent(name)}`}
                    aria-label={t("settings.focus.enableAction", {
                      name: labels.name,
                    })}
                    className="text-sm font-medium text-primary-600 hover:underline"
                  >
                    {t("settings.focus.enableLink")}
                  </Link>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}

interface RenameRow {
  key: string;
  current: string;
  next: string;
}

/**
 * The preview, split into the three things showing one module does: switch
 * off, hide from navigation, rename core labels.
 */
export function FocusDiffPreview({
  diff,
  renameRows,
  describe,
}: {
  diff: FocusModeDiff;
  renameRows: RenameRow[];
  describe: (id: string) => string | null;
}) {
  const { t } = useTranslation("common");
  // Stays enabled but leaves the navigation: every enabled module with a
  // launcher tile except the one being shown.
  const hiddenNames = moduleRegistry
    .getModulesWithLauncher(diff.final_enabled_modules)
    .filter((mod) => mod.name !== diff.focus_module)
    .map((mod) => mod.name);
  // The module's i18n overrides apply the moment the module is enabled, so
  // most "renames" already happened before this screen opened: current and
  // next are the same word, and an arrow between them promises a change the
  // decision cannot make. Only a row the screen can honestly rename stays
  // in the arrow group; the rest are named as already in force.
  const pendingRenames = renameRows.filter((row) => row.current !== row.next);
  const alreadyNamed = renameRows.filter((row) => row.current === row.next);
  return (
    <Card className="p-6" data-testid="focus-diff">
      <h3 className="text-sm font-semibold text-on">
        {t("settings.focus.diffTitle")}
      </h3>
      <dl className="mt-4 grid grid-cols-1 gap-3 text-sm">
        <div>
          <DiffRow
            label={t("settings.focus.diffDisable")}
            items={diff.disable_all}
            variant="remove"
            describe={describe}
          />
          {/* Cascade explanations come from the backend already
              human-readable — render them verbatim, never invent
              reasons client-side. */}
          {diff.warnings && diff.warnings.length > 0 && (
            <div className="mt-1">
              <dt className="text-xs font-medium text-on-muted">
                {t("settings.focus.reasons")}
              </dt>
              <dd>
                <ul className="mt-0.5 list-disc pl-4 space-y-0.5 text-xs text-on-muted">
                  {diff.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </dd>
            </div>
          )}
        </div>
        <DiffRow
          label={t("settings.focus.diffEnableBackground")}
          items={diff.enable}
          variant="neutral"
          describe={describe}
          hint={t("settings.focus.diffEnableBackgroundHint")}
        />
        <DiffRow
          label={t("settings.focus.diffHide")}
          items={hiddenNames}
          variant="neutral"
          describe={describe}
          hint={t("settings.focus.diffHideHint")}
        />
        {pendingRenames.length > 0 && (
          <div>
            <dt className="text-xs font-medium text-on-muted">
              {t("settings.focus.diffRename")}
            </dt>
            <dd className="mt-1 space-y-1">
              {pendingRenames.map((row) => (
                <div
                  key={row.key}
                  className="flex flex-wrap items-center gap-1.5 text-xs"
                >
                  <span className="inline-flex items-center font-medium rounded-md px-2 py-0.5 text-on-secondary bg-surface-raised">
                    {row.current}
                  </span>
                  <ArrowRight size={12} className="text-on-muted shrink-0" />
                  <span className="inline-flex items-center font-medium rounded-md px-2 py-0.5 text-accent-700 bg-accent-50">
                    {row.next}
                  </span>
                </div>
              ))}
            </dd>
          </div>
        )}
        {alreadyNamed.length > 0 && (
          <div>
            <dt className="text-xs font-medium text-on-muted">
              {t("settings.focus.diffRenameAlready")}
            </dt>
            <dd className="mt-1 space-y-1">
              <p className="text-xs text-on-muted">
                {t("settings.focus.diffRenameAlreadyHint")}
              </p>
              {alreadyNamed.map((row) => (
                <div
                  key={row.key}
                  className="flex flex-wrap items-center text-xs"
                >
                  <span className="inline-flex items-center font-medium rounded-md px-2 py-0.5 text-accent-700 bg-accent-50">
                    {row.next}
                  </span>
                </div>
              ))}
            </dd>
          </div>
        )}
      </dl>
    </Card>
  );
}

interface DiffRowProps {
  label: string;
  items: string[];
  variant: "remove" | "neutral";
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
    variant === "remove"
      ? "text-rose-700 bg-rose-50"
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
