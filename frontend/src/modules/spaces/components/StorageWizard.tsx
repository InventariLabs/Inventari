/**
 * StorageWizard — mobile-first bottom sheet for adding storage locations.
 *
 * Flow:
 *   Step 1 — Zone: pick existing zone OR type a new name (i18n chips)
 *   Step 2 — Location name + tracking-fields preview (tap ✓ Gotowe to save)
 *   Step 3 — (optional) Field checkboxes to customise tracking fields
 *
 * First-run mode: fullscreen onboarding when the org has no zones yet.
 *
 * The sheet is the shared `Sheet` — first run full-bleed, otherwise a bottom
 * sheet on a phone and a centred dialog on a desktop — so the keyboard, the
 * focus and the layer are the same as everywhere else. Escape, the cross and
 * the backdrop are one exit: a step holding something typed asks before it is
 * thrown away, an empty one closes at once.
 */
import { useState, useRef, useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { X, ChevronLeft, Loader2, Check } from "lucide-react";
import { FieldDefinition } from "@/types";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import { extractApiError } from "@/lib/errors";
import { Button } from "@/components/ui/Button";
import { useFieldBuilderCommit } from "@/components/ui/FieldBuilder";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Sheet, SheetBody, SheetFooter } from "@/components/ui/Sheet";
import { useLocationOffer, useLocationsById } from "@/module-sdk";
import { useExistingLocations } from "@/modules/shared/hooks/useExistingLocations";
import { useStorageTypes } from "@/modules/shared/hooks/useStorages";
import { useCreateStorageHierarchy } from "@/modules/shared/hooks/useStorageMutations";
import { Step, StepContent } from "./StorageWizardStepContent";
import { defaultTrackingFieldsForLocation } from "@/modules/spaces/utils/defaultTrackingFields";
import { useWizardSuggestions } from "@/modules/shared/hooks/useWizardSuggestions";

interface StorageWizardProps {
  isOpen: boolean;
  onClose: () => void;
  /** Pre-select a zone — used by contextual "+ Add here" button in zone view */
  preselectedParentId?: string;
}

/** Wizard step titles; extracted to keep the component within the lint line budget. */
function useWizardStepTitles(parentLabel: string | null) {
  const { t } = useTranslation(["locations", "common"]);
  return [
    t("onboarding.step1Title"),
    parentLabel
      ? `${t("onboarding.step2Title")} — ${parentLabel}`
      : t("onboarding.step2Title"),
    t("onboarding.step3Title"),
  ];
}

/** Focus management for the wizard steps; extracted for the lint line budget. */
function useWizardStepFocus(
  step: Step,
  parentInputRef: React.RefObject<HTMLInputElement>,
  locationInputRef: React.RefObject<HTMLInputElement>,
) {
  useEffect(() => {
    if (step === 1) setTimeout(() => parentInputRef.current?.focus(), 50);
    if (step === 2) setTimeout(() => locationInputRef.current?.focus(), 50);
  }, [step, parentInputRef, locationInputRef]);
}

interface WizardHeaderProps {
  step: Step;
  title: string;
  /** Fullscreen onboarding wears the quieter chrome of a first-run screen. */
  firstRun: boolean;
  canGoBack: boolean;
  backLabel: string;
  closeLabel: string;
  onBack: () => void;
  onClose: () => void;
}

/** The sheet's title row: the way back a step, the step's title, and the exit. */
function WizardHeader({
  step,
  title,
  firstRun,
  canGoBack,
  backLabel,
  closeLabel,
  onBack,
  onClose,
}: WizardHeaderProps) {
  const iconSize = firstRun ? 20 : 18;
  return (
    <div
      className={cn(
        "flex items-center justify-between flex-shrink-0",
        firstRun ? "px-4 pt-4 pb-3 border-b border-border" : "px-5 pb-3",
      )}
    >
      <div className="flex items-center gap-3">
        {canGoBack && (
          <Button
            variant="ghost"
            size="icon"
            onClick={onBack}
            aria-label={backLabel}
          >
            <ChevronLeft size={iconSize} />
          </Button>
        )}
        <div>
          {firstRun ? (
            <p className="text-sm font-semibold text-on-secondary">{title}</p>
          ) : (
            <h2 className="font-semibold text-on text-base leading-tight">
              {title}
            </h2>
          )}
          <div
            className={cn("flex gap-1.5 w-full", firstRun ? "mt-1" : "mt-1.5")}
          >
            {[1, 2, 3].map((s) => (
              <div
                key={s}
                className={`h-1.5 flex-1 rounded-full transition-all ${
                  s <= step ? "bg-primary-500" : "bg-surface-inset"
                }`}
              />
            ))}
          </div>
        </div>
      </div>
      <Button
        variant="ghost"
        size="icon"
        onClick={onClose}
        aria-label={closeLabel}
      >
        <X size={iconSize} />
      </Button>
    </div>
  );
}

/** Resets the wizard to its opening state; extracted for the lint line budget. */
function useWizardResetOnOpen(
  isOpen: boolean,
  preselectedParentId: string | undefined,
  setStep: (s: Step) => void,
  setParentId: (id: string | null) => void,
) {
  useEffect(() => {
    if (!isOpen) return;
    if (preselectedParentId) {
      setStep(2);
      setParentId(preselectedParentId);
    } else {
      setStep(1);
    }
  }, [isOpen, preselectedParentId, setStep, setParentId]);
}

/** The wizard's answers, as the question "is there anything to lose?" sees them. */
interface WizardDraft {
  preselectedParentId?: string;
  parentId: string | null;
  parentName: string;
  locationName: string;
  selectedFields: string[] | null;
  customFields: FieldDefinition[];
  labelCode: string;
  description: string;
  storageTypeId: string | null;
}

/**
 * Whether a step holds something the reader has put there.
 *
 * A parent this screen was *given* is not theirs: "+ Add here" opens the
 * wizard on a location they picked to put something inside, and until they
 * type, there is nothing to lose.
 */
function hasStepData({
  preselectedParentId,
  parentId,
  parentName,
  locationName,
  selectedFields,
  customFields,
  labelCode,
  description,
  storageTypeId,
}: WizardDraft): boolean {
  return (
    parentName.trim().length > 0 ||
    (parentId !== null && parentId !== preselectedParentId) ||
    locationName.trim().length > 0 ||
    selectedFields !== null ||
    customFields.length > 0 ||
    labelCode.trim().length > 0 ||
    description.trim().length > 0 ||
    storageTypeId !== null
  );
}

/**
 * The two small reads the first step stands on: how many places there are,
 * and the names at the two levels the suggestions are checked against. Either
 * failing is one failed load of the parent choices, never a shorter list.
 */
function useWizardParents(parentId: string | null) {
  const offer = useLocationOffer({ purpose: "general" });
  const existing = useExistingLocations(parentId);
  const failed = offer.isError || existing.isError;
  return {
    offer,
    existing,
    error: failed ? (offer.error ?? existing.error) : null,
    refetch: () => {
      offer.refetch();
      existing.refetch();
    },
  };
}

/**
 * Whether this organization has nothing yet. An empty answer and no answer are
 * not the same claim: only the first means there is nothing here — and
 * "nothing" is a flat list, because every organization is handed a default
 * top-level location whether it asked for one or not. Said only once both
 * answers are in: the full-screen first run is not the layout to flash at an
 * organization that already has a structure.
 */
function useWizardFirstRun(
  total: number | undefined,
  topLevelTotal: number | undefined,
  failed: boolean,
): boolean {
  if (total === undefined || topLevelTotal === undefined || failed)
    return false;
  return total <= topLevelTotal;
}

export default function StorageWizard({
  isOpen,
  onClose,
  preselectedParentId,
}: StorageWizardProps) {
  const { t } = useTranslation(["locations", "common"]);

  const [step, setStep] = useState<Step>(preselectedParentId ? 2 : 1);
  const [parentId, setParentId] = useState<string | null>(
    preselectedParentId ?? null,
  );
  const [parentName, setParentName] = useState("");
  const [locationName, setLocationName] = useState("");
  /**
   * null  = use auto-defaults from defaultFieldsForName(locationName)
   * array = user has explicitly customised fields in step 3
   */
  const [selectedFields, setSelectedFields] = useState<string[] | null>(null);
  const [customFields, setCustomFields] = useState<FieldDefinition[]>([]);
  const fieldBuilder = useFieldBuilderCommit(customFields);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [labelCode, setLabelCode] = useState("");
  const [description, setDescription] = useState("");
  const [storageTypeId, setStorageTypeId] = useState<string | null>(null);
  const [discardConfirmOpen, setDiscardConfirmOpen] = useState(false);
  const parentInputRef = useRef<HTMLInputElement>(null);
  const locationInputRef = useRef<HTMLInputElement>(null);

  // ADR-018: any location can hold another, so step 1 offers all of them
  // rather than the children of a top-level one. A shelf three levels down is
  // a parent like any other, and the path under each name is what tells two
  // shelves called "Top" apart. "All of them" is the same slice the list this
  // wizard was opened from shows: the organization's own locations, without
  // the ones a vertical module owns while its data is hidden here. The
  // picker searches that slice on the server; the wizard itself only needs
  // to know how many places there are, which one was chosen, and the names
  // standing at the two levels its suggestions are checked against.
  const {
    offer,
    existing,
    error: storagesError,
    refetch: refetchStorages,
  } = useWizardParents(parentId);
  const hasParents = (offer.total ?? 0) > 0;
  const named = useLocationsById(parentId ? [parentId] : []);
  const {
    data: storageTypes = [],
    error: typesError,
    refetch: refetchTypes,
  } = useStorageTypes();

  const selectedParent = named.byId.get(parentId ?? "");
  const { locationSuggestions, filteredParentSuggestions } =
    useWizardSuggestions(existing.rows, selectedParent);

  const isFirstRun =
    useWizardFirstRun(offer.total, existing.topLevelTotal, !!storagesError) &&
    !preselectedParentId;
  const parentLabel = selectedParent?.name ?? (parentName.trim() || null);
  const canProceedStep1 = parentId !== null || parentName.trim().length > 0;
  // Done works without a leaf when step 1 named something new — that name is
  // the location being created. Picking one that already exists and stopping
  // there creates nothing, and the wizard would report success for it.
  const canProceedStep2 = parentId === null || locationName.trim().length > 0;

  // Effective tracking fields: user-customised or neutral default.
  // no name-based heuristic — vertical fields come from category.
  const effectiveFields = useMemo(
    () => selectedFields ?? [...defaultTrackingFieldsForLocation(locationName)],
    [selectedFields, locationName],
  );

  useWizardResetOnOpen(isOpen, preselectedParentId, setStep, setParentId);

  useWizardStepFocus(step, parentInputRef, locationInputRef);

  const hierarchyMutation = useCreateStorageHierarchy();

  // a storage type seeds the default tracking fields; the user's
  // manual field selection stays an override of the type defaults.
  const handleStorageTypeChange = (typeId: string) => {
    setStorageTypeId(typeId || null);
    const type = storageTypes.find((st) => st.id === typeId);
    if (type?.context_schema && type.context_schema.length > 0) {
      setSelectedFields(type.context_schema);
    }
  };

  const buildHierarchyData = (fieldDefinitions: FieldDefinition[]) => ({
    // The chain is the structure; no leaf step finishes on the location the
    // first step reached, so someone wanting one place does not have to
    // invent a second one inside it (ADR-018).
    steps: [
      parentId ? { id: parentId } : { name: parentName.trim() },
      ...(locationName.trim() ? [{ name: locationName.trim() }] : []),
    ],
    context_schema: effectiveFields,
    field_definitions:
      fieldDefinitions.length > 0 ? fieldDefinitions : undefined,
    short_code: labelCode.trim() || undefined,
    description: description.trim() || undefined,
    location_type_id: storageTypeId ?? undefined,
  });

  const submitHierarchy = () => {
    // A field typed into the builder and not confirmed is part of what the
    // reader is creating: it joins the list, or the creation waits for them
    // to finish it.
    const fieldDefinitions = fieldBuilder.commit();
    if (!fieldDefinitions) return;
    hierarchyMutation.mutate(buildHierarchyData(fieldDefinitions), {
      onSuccess: () => {
        toast.success(t("messages.storageCreated"));
        handleClose();
      },
      onError: (error: unknown) => {
        toast.error(extractApiError(error, t("unknownError")));
      },
    });
  };

  const resetForm = () => {
    setStep(preselectedParentId ? 2 : 1);
    setParentId(preselectedParentId ?? null);
    setParentName("");
    setLocationName("");
    setSelectedFields(null);
    setCustomFields([]);
    setLabelCode("");
    setDescription("");
    setStorageTypeId(null);
    setShowAdvanced(false);
  };

  const handleClose = () => {
    resetForm();
    onClose();
  };

  /**
   * Anything the reader has put into the three steps — the two names, the
   * tracking fields, the advanced ones.
   */
  const stepHasData = hasStepData({
    preselectedParentId,
    parentId,
    parentName,
    locationName,
    selectedFields,
    customFields,
    labelCode,
    description,
    storageTypeId,
  });

  /**
   * Every way out of the sheet comes through here: the key, the cross and the
   * backdrop. An empty step leaves at once; a step holding something typed is
   * never thrown away without a word.
   */
  const requestClose = () => {
    if (stepHasData) {
      setDiscardConfirmOpen(true);
      return;
    }
    handleClose();
  };

  const goNext = () => {
    if (step === 1 && canProceedStep1) setStep(2);
    else if (step === 2 && canProceedStep2) submitHierarchy();
    else if (step === 3) submitHierarchy();
  };

  const goBack = () => {
    if (step === 2 && !preselectedParentId) {
      setLocationName("");
      setSelectedFields(null);
      setStep(1);
    } else if (step === 3) setStep(2);
  };

  const stepTitles = useWizardStepTitles(parentLabel);

  if (!isOpen) return null;

  const isDisabled =
    (step === 1 && !canProceedStep1) ||
    (step === 2 && !canProceedStep2) ||
    hierarchyMutation.isPending;

  const stepContent = (
    <StepContent
      step={step}
      parentId={parentId}
      parentName={parentName}
      locationName={locationName}
      selectedFields={selectedFields}
      effectiveFields={effectiveFields}
      customFields={customFields}
      fieldBuilderRef={fieldBuilder.ref}
      hasParents={hasParents}
      filteredParentSuggestions={filteredParentSuggestions}
      locationSuggestions={locationSuggestions}
      parentInputRef={parentInputRef}
      locationInputRef={locationInputRef}
      showAdvanced={showAdvanced}
      labelCode={labelCode}
      description={description}
      storageTypes={storageTypes}
      parentsError={storagesError}
      onRetryParents={refetchStorages}
      typesError={typesError}
      onRetryTypes={() => void refetchTypes()}
      storageTypeId={storageTypeId}
      onStorageTypeChange={handleStorageTypeChange}
      onSelectParent={(id) => {
        setParentId(id);
        setParentName("");
        setLocationName("");
        setSelectedFields(null);
        setStep(2);
      }}
      onParentChip={(name) => {
        setParentId(null);
        setParentName(name);
        setLocationName("");
        setSelectedFields(null);
        setStep(2);
      }}
      onParentNameChange={(v) => {
        setParentName(v);
        setParentId(null);
      }}
      onLocationNameChange={(v) => {
        setLocationName(v);
        setSelectedFields(null);
      }}
      onLocationChip={(v) => {
        setLocationName(v);
        setSelectedFields(null);
      }}
      onFieldsChange={setSelectedFields}
      onCustomFieldsChange={setCustomFields}
      onCustomize={() => setStep(3)}
      onToggleAdvanced={() => setShowAdvanced(!showAdvanced)}
      onLabelCodeChange={setLabelCode}
      onDescriptionChange={setDescription}
      t={t}
    />
  );

  const footer = (
    <Button disabled={isDisabled} onClick={goNext} className="w-full">
      {hierarchyMutation.isPending ? (
        <Loader2 size={20} className="animate-spin" />
      ) : step === 2 || step === 3 ? (
        <>
          <Check size={20} /> {t("onboarding.done")}
        </>
      ) : (
        t("onboarding.next")
      )}
    </Button>
  );

  return (
    <Sheet
      open
      onClose={requestClose}
      zIndex="fullscreen"
      maxWidth="lg"
      backdropOpacity={50}
      // First run takes the whole screen, as it always has; every other visit
      // is a bottom sheet on a phone and a centred dialog above `sm`.
      fullBleed={isFirstRun}
      aria-label={t("wizard.title")}
    >
      {!isFirstRun && (
        <>
          {/* drag handle — mobile only */}
          <div className="flex justify-center pt-3 pb-1 flex-shrink-0 sm:hidden">
            <div className="w-10 h-1 rounded-full bg-surface-inset" />
          </div>
          <div className="hidden sm:block pt-5 flex-shrink-0" />
        </>
      )}

      <WizardHeader
        step={step}
        title={stepTitles[step - 1]}
        firstRun={isFirstRun}
        canGoBack={step > 1 && !preselectedParentId}
        backLabel={t("onboarding.back", { defaultValue: "Back" })}
        closeLabel={t("common:a11y.close")}
        onBack={goBack}
        onClose={requestClose}
      />

      <SheetBody className={isFirstRun ? "px-5 py-6" : "px-5"}>
        {stepContent}
      </SheetBody>

      <SheetFooter>{footer}</SheetFooter>

      <ConfirmDialog
        open={discardConfirmOpen}
        zIndex="fullscreen"
        variant="danger"
        title={t("wizard.discardTitle")}
        message={t("wizard.discardMessage")}
        confirmLabel={t("wizard.discardConfirm")}
        cancelLabel={t("wizard.discardCancel")}
        onConfirm={() => {
          setDiscardConfirmOpen(false);
          handleClose();
        }}
        onCancel={() => setDiscardConfirmOpen(false)}
      />
    </Sheet>
  );
}
