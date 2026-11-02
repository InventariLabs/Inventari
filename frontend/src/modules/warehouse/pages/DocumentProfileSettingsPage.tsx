import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/Button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import LoadingSpinner from "@/components/LoadingSpinner";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanManage, useCanWrite } from "@/hooks/useCanWrite";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import {
  PageSaveProvider,
  SettingsSaveBar,
  usePageSavePart,
} from "@/module-sdk";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import {
  useDocumentProfile,
  useDocumentPresets,
  useUpdateDocumentProfile,
  useApplyDocumentPreset,
} from "@/modules/warehouse/hooks/useDocumentProfile";
import { usePresetApply } from "@/modules/warehouse/hooks/usePresetApply";
import {
  buildProfileUpdate,
  useDocumentProfileDraft,
} from "@/modules/warehouse/hooks/useDocumentProfileDraft";
import {
  ApprovalsPanel,
  FloorPanel,
  NumberingPanel,
  PresetsPanel,
  PrintoutsPanel,
  PutawayPanel,
  ReceivingPanel,
  TrackingPanel,
} from "@/modules/warehouse/components/ConfigurationPanels";
import { ReceivingSettingsSection } from "@/modules/warehouse/components/ReceivingSettingsSection";

const SECTIONS = [
  "receiving",
  "putaway",
  "printouts",
  "numbering",
  "approvals",
  "floor",
  "tracking",
  "presets",
] as const;
type Section = (typeof SECTIONS)[number];

/** The screen when the profile did not load. The receiving tolerance is its
 * own query: the profile failing says nothing about it, so it stays where it
 * was. */
function ProfileLoadFailed({ onRetry }: { onRetry: () => void }) {
  const { t } = useTranslation("warehouse");
  const { t: ct } = useTranslation("common");
  return (
    <div className="space-y-8">
      <ReceivingSettingsSection />
      <SettingsSaveBar
        guardLabel={t("profile.guardName")}
        successMessage={t("profile.saveSuccess")}
        failureMessage={t("profile.saveFailed")}
      />
      <div className="flex flex-col items-center justify-center py-20 gap-4">
        <div className="w-16 h-16 bg-red-100 text-red-600 rounded-full flex items-center justify-center">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="28"
            height="28"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
        </div>
        <p className="text-sm text-on-secondary max-w-md text-center">
          {t("profile.loadFailed", {
            defaultValue: "Failed to load profile settings. Please try again.",
          })}
        </p>
        <Button variant="outline" size="sm" onClick={onRetry}>
          {ct("actions.retry", { defaultValue: "Retry" })}
        </Button>
      </div>
    </div>
  );
}

export default function DocumentProfileSettingsPage() {
  // The provider is the page's one Save: every section below registers its
  // edit with it, and `SettingsSaveBar` writes them together.
  return (
    <PageSaveProvider>
      <ConfigurationPage />
    </PageSaveProvider>
  );
}

function ConfigurationPage() {
  const { t } = useTranslation("warehouse");
  const { setHeader } = useModulePageHeader();
  const canManage = useCanManage("warehouse");
  // The per-warehouse receiving choice is written under the module's write grant.
  const canWrite = useCanWrite("warehouse");
  const wide = useMediaQuery("(min-width: 768px)");
  const [params, setParams] = useSearchParams();
  const asked = params.get("section");
  const section: Section = SECTIONS.includes(asked as Section)
    ? (asked as Section)
    : "receiving";

  const { data: profile, isLoading, isError, refetch } = useDocumentProfile();
  const {
    data: presets = [],
    isError: presetsFailed,
    error: presetsError,
    refetch: refetchPresets,
  } = useDocumentPresets();
  const updateMutation = useUpdateDocumentProfile();
  const applyPresetMutation = useApplyDocumentPreset();

  const draft = useDocumentProfileDraft(profile);
  const { selectedPreset, setSelectedPreset, isDirty, syncLocalState } = draft;

  useEffect(() => {
    setHeader({
      title: t("settings.moduleTitle"),
      subtitle: t("settings.moduleSubtitle"),
    });
  }, [t, setHeader]);

  const { applyPreset, confirmDialogProps } = usePresetApply({
    profile,
    syncLocalState,
    applyPresetMutation,
    updateMutation,
  });

  // The select already shows the picked name — the change fired before the
  // question — so a refusal has to put it back to the row that still stands.
  const handleApplyPreset = async (presetName: string) => {
    const { declined, restoredName } = await applyPreset(presetName);
    if (declined) setSelectedPreset(restoredName);
  };

  // The profile form's share of the page's Save. The request's own refusal is
  // reported by the bar, through extractApiError.
  usePageSavePart("profile", isDirty, async () => {
    const saved = await updateMutation.mutateAsync(
      buildProfileUpdate(draft.draft),
    );
    syncLocalState(saved);
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <LoadingSpinner />
      </div>
    );
  }

  if (isError) return <ProfileLoadFailed onRetry={() => refetch()} />;

  // Static keys, so the catalogue check can see each one is read.
  const labels: Record<Section, string> = {
    receiving: t("configuration.sections.receiving"),
    putaway: t("configuration.sections.putaway"),
    printouts: t("configuration.sections.printouts"),
    numbering: t("configuration.sections.numbering"),
    approvals: t("configuration.sections.approvals"),
    floor: t("configuration.sections.floor"),
    tracking: t("configuration.sections.tracking"),
    presets: t("configuration.sections.presets"),
  };

  const panels: Record<Section, React.ReactNode> = {
    receiving: <ReceivingPanel d={draft} />,
    putaway: <PutawayPanel canWrite={canWrite} />,
    printouts: <PrintoutsPanel />,
    numbering: <NumberingPanel d={draft} />,
    approvals: <ApprovalsPanel d={draft} />,
    floor: <FloorPanel d={draft} />,
    tracking: <TrackingPanel />,
    presets: (
      <PresetsPanel
        selectedPreset={selectedPreset}
        presets={presets}
        isPending={applyPresetMutation.isPending}
        onChange={setSelectedPreset}
        onApply={handleApplyPreset}
        failed={presetsFailed}
        error={presetsError}
        onRetry={() => void refetchPresets()}
      />
    ),
  };

  return (
    // no ad-hoc max-w at the view root — ModuleShell owns padding;
    // like the rest of the module, the page spans the available width.
    <div className="space-y-6 pb-8 animate-in fade-in duration-300">
      {/* The form below stays readable — knowing how the organization has
          its documents set up is not administration. Only the Save is. */}
      <ReadOnlyNotice module="warehouse" right="manage" />
      <Tabs
        defaultValue="receiving"
        value={section}
        onValueChange={(next) =>
          setParams({ section: next }, { replace: true })
        }
        orientation={wide ? "vertical" : "horizontal"}
        className="md:flex md:items-start md:gap-6"
      >
        <TabsList
          aria-label={t("configuration.nav")}
          className="w-full md:sticky md:top-2 md:w-64 md:shrink-0 md:flex-col md:items-stretch md:[justify-content:flex-start]"
        >
          {SECTIONS.map((key) => (
            <TabsTrigger
              key={key}
              value={key}
              className="md:w-full md:justify-start"
            >
              {labels[key]}
            </TabsTrigger>
          ))}
        </TabsList>
        <div className="min-w-0 flex-1">
          {/* One fieldset rather than a `disabled` on every control, because
              the next control added is disabled by having been added. Every
              panel stays mounted (`forceMount`): an edit made in one section
              must still be waiting for Save after the reader moves to another.
              `min-w-0` because a fieldset defaults to min-content. */}
          <fieldset disabled={!canManage} className="m-0 min-w-0 border-0 p-0">
            {SECTIONS.map((key) => (
              <TabsContent
                key={key}
                value={key}
                forceMount
                // Radix leaves a force-mounted panel visible; the attribute is
                // what takes the other sections off the screen.
                hidden={key !== section}
                className="mt-4 space-y-6 md:mt-0"
              >
                {panels[key]}
              </TabsContent>
            ))}
          </fieldset>
        </div>
      </Tabs>
      {canManage && (
        <SettingsSaveBar
          guardLabel={t("profile.guardName")}
          successMessage={t("profile.saveSuccess")}
          failureMessage={t("profile.saveFailed")}
        />
      )}
      <ConfirmDialog {...confirmDialogProps} />
    </div>
  );
}
