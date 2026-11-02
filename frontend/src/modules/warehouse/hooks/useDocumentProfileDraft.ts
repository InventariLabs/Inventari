import { useCallback, useEffect, useRef, useState } from "react";
import type {
  DocumentProfile,
  DocumentProfileUpdate,
  TaxHandling,
} from "@/modules/warehouse/types";

const toString = (v: string | number | null | undefined): string => {
  if (v === null || v === undefined) return "";
  return String(v);
};

/** The profile screen's whole draft — every field it holds state for. */
export interface ProfileDraft {
  valueTracking: boolean;
  taxHandling: TaxHandling;
  defaultTaxRate: string;
  requireTaxId: boolean | null;
  requireUnitPrice: boolean;
  confirmShelfByScan: boolean;
  quarantineLocationId: string;
  numberingFormat: string;
  numberPadding: number;
  typeLabelIN: string;
  typeLabelOUT: string;
  typeLabelINT: string;
  typeLabelInternalIn: string;
  typeLabelInternalOut: string;
  typeLabelCORR: string;
  typeLabelSCRAP: string;
  typeLabelADJ: string;
  defaultCurrency: string;
  approvalThreshold: string;
  approvalRequiredTypes: string[];
}

function anyDiffers(pairs: Array<[unknown, unknown]>): boolean {
  return pairs.some(([drafted, saved]) => drafted !== saved);
}

/**
 * Does this draft hold anything the saved profile does not? Compared field by
 * field with the profile the query holds — not with a snapshot taken at mount:
 * a refetch that brings a new saved value leaves a different draft dirty,
 * which is the truth.
 */
function draftDiffers(draft: ProfileDraft, profile: DocumentProfile): boolean {
  return anyDiffers([
    [draft.valueTracking, profile.value_tracking_enabled],
    [draft.taxHandling, profile.tax_handling as TaxHandling],
    [draft.defaultTaxRate, toString(profile.default_tax_rate)],
    [draft.requireTaxId, profile.require_partner_tax_id],
    // The saved side is counted the way the screen and the payload count
    // it: the requirement only stands while value tracking is on. A row
    // saved with value tracking off and the requirement still in the
    // column — the reachable state the disabled checkbox exists for — then
    // loads as clean, which is the truth: nothing on this page was edited.
    // The other half of the pair is already the valueTracking comparison
    // above, so turning tracking off still arms the gate.
    [
      draft.requireUnitPrice,
      profile.require_unit_price && profile.value_tracking_enabled,
    ],
    [draft.confirmShelfByScan, profile.confirm_shelf_by_scan],
    [draft.quarantineLocationId, profile.quarantine_location_id ?? ""],
    [draft.numberingFormat, profile.numbering_format],
    [draft.numberPadding, profile.number_padding],
    [draft.typeLabelIN, profile.type_labels?.IN ?? ""],
    [draft.typeLabelOUT, profile.type_labels?.OUT ?? ""],
    [draft.typeLabelINT, profile.type_labels?.INT ?? ""],
    [draft.typeLabelInternalIn, profile.type_labels?.INTERNAL_IN ?? ""],
    [draft.typeLabelInternalOut, profile.type_labels?.INTERNAL_OUT ?? ""],
    [draft.typeLabelCORR, profile.type_labels?.CORRECTION ?? ""],
    [draft.typeLabelSCRAP, profile.type_labels?.SCRAP ?? ""],
    [draft.typeLabelADJ, profile.type_labels?.ADJUSTMENT ?? ""],
    [draft.defaultCurrency, toString(profile.default_currency ?? "")],
    [draft.approvalThreshold, toString(profile.approval_threshold)],
    [
      draft.approvalRequiredTypes.join("\u0000"),
      (profile.approval_required_for_types ?? []).join("\u0000"),
    ],
  ]);
}

export function buildProfileUpdate(draft: ProfileDraft): DocumentProfileUpdate {
  const typeLabels: Record<string, string> = {};
  if (draft.typeLabelIN.trim()) typeLabels.IN = draft.typeLabelIN.trim();
  if (draft.typeLabelOUT.trim()) typeLabels.OUT = draft.typeLabelOUT.trim();
  if (draft.typeLabelINT.trim()) typeLabels.INT = draft.typeLabelINT.trim();
  if (draft.typeLabelInternalIn.trim())
    typeLabels.INTERNAL_IN = draft.typeLabelInternalIn.trim();
  if (draft.typeLabelInternalOut.trim())
    typeLabels.INTERNAL_OUT = draft.typeLabelInternalOut.trim();
  if (draft.typeLabelCORR.trim())
    typeLabels.CORRECTION = draft.typeLabelCORR.trim();
  if (draft.typeLabelSCRAP.trim())
    typeLabels.SCRAP = draft.typeLabelSCRAP.trim();
  if (draft.typeLabelADJ.trim())
    typeLabels.ADJUSTMENT = draft.typeLabelADJ.trim();

  return {
    value_tracking_enabled: draft.valueTracking,
    tax_handling: draft.taxHandling,
    default_tax_rate: toString(draft.defaultTaxRate).trim() || null,
    require_partner_tax_id: draft.requireTaxId,
    // A price cannot be required on lines whose form shows no price: that
    // combination leaves documents nobody can save. The checkbox exists
    // only while value tracking is on, so the draft and this payload agree
    // with the screen — switching value tracking off takes the
    // requirement with it rather than leaving it standing in the column.
    require_unit_price: draft.valueTracking && draft.requireUnitPrice,
    confirm_shelf_by_scan: draft.confirmShelfByScan,
    quarantine_location_id: draft.quarantineLocationId || null,
    numbering_format: draft.numberingFormat.trim() || undefined,
    number_padding: draft.numberPadding,
    type_labels: Object.keys(typeLabels).length > 0 ? typeLabels : null,
    default_currency:
      toString(draft.defaultCurrency).trim().toUpperCase() || null,
    approval_threshold: toString(draft.approvalThreshold).trim() || null,
    // Always the array, empty included. `undefined` drops the key from a
    // JSON body, the backend reads presence off the key set, and an emptied
    // list could then never be saved — unticking the last type used to
    // leave the old list standing.
    approval_required_for_types: draft.approvalRequiredTypes,
  };
}

/**
 * The screen's fields, their draft, and whether that draft differs from the
 * saved profile. Kept beside the screen rather than inside its component: the
 * form grew past the one-function size the linter allows, and state plus the
 * save payload are one responsibility while the grouped form is another.
 */
export function useDocumentProfileDraft(profile: DocumentProfile | undefined) {
  const [selectedPreset, setSelectedPreset] = useState("");
  const profileSyncedRef = useRef(false);
  // The draft starts as empty defaults and takes the profile's values in an
  // effect, so for one render a loaded profile differs from it. Nothing has
  // been edited then, and the page's Save must not flash.
  const [synced, setSynced] = useState(false);

  const [valueTracking, setValueTracking] = useState(false);
  const [taxHandling, setTaxHandling] = useState<TaxHandling>("NONE");
  const [defaultTaxRate, setDefaultTaxRate] = useState("");
  const [requireTaxId, setRequireTaxId] = useState<boolean | null>(false);
  const [requireUnitPrice, setRequireUnitPrice] = useState(false);
  const [confirmShelfByScan, setConfirmShelfByScan] = useState(false);
  const [quarantineLocationId, setQuarantineLocationId] = useState("");
  const [numberingFormat, setNumberingFormat] = useState("");
  const [numberPadding, setNumberPadding] = useState(4);
  const [typeLabelIN, setTypeLabelIN] = useState("");
  const [typeLabelOUT, setTypeLabelOUT] = useState("");
  const [typeLabelINT, setTypeLabelINT] = useState("");
  const [typeLabelInternalIn, setTypeLabelInternalIn] = useState("");
  const [typeLabelInternalOut, setTypeLabelInternalOut] = useState("");
  const [typeLabelCORR, setTypeLabelCORR] = useState("");
  const [typeLabelSCRAP, setTypeLabelSCRAP] = useState("");
  const [typeLabelADJ, setTypeLabelADJ] = useState("");
  const [defaultCurrency, setDefaultCurrency] = useState("");
  const [approvalThreshold, setApprovalThreshold] = useState("");
  const [approvalRequiredTypes, setApprovalRequiredTypes] = useState<string[]>(
    [],
  );

  const syncLocalState = useCallback((p: DocumentProfile) => {
    setSelectedPreset(p.name ?? "");
    setValueTracking(p.value_tracking_enabled);
    setTaxHandling(p.tax_handling as TaxHandling);
    setDefaultTaxRate(toString(p.default_tax_rate));
    setRequireTaxId(p.require_partner_tax_id);
    setRequireUnitPrice(p.require_unit_price);
    setConfirmShelfByScan(p.confirm_shelf_by_scan);
    setQuarantineLocationId(p.quarantine_location_id ?? "");
    setNumberingFormat(p.numbering_format);
    setNumberPadding(p.number_padding);
    setTypeLabelIN(p.type_labels?.IN ?? "");
    setTypeLabelOUT(p.type_labels?.OUT ?? "");
    setTypeLabelINT(p.type_labels?.INT ?? "");
    setTypeLabelInternalIn(p.type_labels?.INTERNAL_IN ?? "");
    setTypeLabelInternalOut(p.type_labels?.INTERNAL_OUT ?? "");
    setTypeLabelCORR(p.type_labels?.CORRECTION ?? "");
    setTypeLabelSCRAP(p.type_labels?.SCRAP ?? "");
    setTypeLabelADJ(p.type_labels?.ADJUSTMENT ?? "");
    setDefaultCurrency(p.default_currency ?? "");
    setApprovalThreshold(toString(p.approval_threshold));
    setApprovalRequiredTypes(
      Array.isArray(p.approval_required_for_types)
        ? p.approval_required_for_types
        : [],
    );
  }, []);

  useEffect(() => {
    if (!profile || profileSyncedRef.current) return;
    profileSyncedRef.current = true;
    syncLocalState(profile);
    setSynced(true);
  }, [profile, syncLocalState]);

  // What the page's one Save sends. `isDirty` below says whether it differs
  // from the profile the query holds, which is what offers Save and arms the
  // leave question.
  const draft: ProfileDraft = {
    valueTracking,
    taxHandling,
    defaultTaxRate,
    requireTaxId,
    // Gated here exactly as it is in the payload: with value tracking off
    // the checkbox is disabled and reads unchecked, and a draft that
    // disagreed with the screen would save something else than it shows.
    requireUnitPrice: valueTracking && requireUnitPrice,
    confirmShelfByScan,
    quarantineLocationId,
    numberingFormat,
    numberPadding,
    typeLabelIN,
    typeLabelOUT,
    typeLabelINT,
    typeLabelInternalIn,
    typeLabelInternalOut,
    typeLabelCORR,
    typeLabelSCRAP,
    typeLabelADJ,
    defaultCurrency,
    approvalThreshold,
    approvalRequiredTypes,
  };
  const isDirty = synced && !!profile && draftDiffers(draft, profile);

  return {
    selectedPreset,
    setSelectedPreset,
    valueTracking,
    setValueTracking,
    taxHandling,
    setTaxHandling,
    defaultTaxRate,
    setDefaultTaxRate,
    requireTaxId,
    setRequireTaxId,
    requireUnitPrice,
    setRequireUnitPrice,
    confirmShelfByScan,
    setConfirmShelfByScan,
    quarantineLocationId,
    setQuarantineLocationId,
    numberingFormat,
    setNumberingFormat,
    numberPadding,
    setNumberPadding,
    typeLabelIN,
    setTypeLabelIN,
    typeLabelOUT,
    setTypeLabelOUT,
    typeLabelINT,
    setTypeLabelINT,
    typeLabelInternalIn,
    setTypeLabelInternalIn,
    typeLabelInternalOut,
    setTypeLabelInternalOut,
    typeLabelCORR,
    setTypeLabelCORR,
    typeLabelSCRAP,
    setTypeLabelSCRAP,
    typeLabelADJ,
    setTypeLabelADJ,
    defaultCurrency,
    setDefaultCurrency,
    approvalThreshold,
    setApprovalThreshold,
    approvalRequiredTypes,
    setApprovalRequiredTypes,
    draft,
    isDirty,
    syncLocalState,
  };
}
