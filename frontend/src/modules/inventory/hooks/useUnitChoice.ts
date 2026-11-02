import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { findUom, useUoms } from "@/modules/shared/hooks/useUoms";
import { useTemplateUnitHint } from "./useTemplateUnitHint";

/**
 * The unit the matched product template keeps, as the form shows it.
 *
 * It travels with the form so the hint can sit beside the picker — "this
 * product is kept in kg" before anything is saved — and so a save can tell a
 * deliberate choice from the template's own unit.
 */
export interface TemplateUnitPrompt {
  /** The matched product (its name, which may differ from the typed one). */
  productName: string;
  /** The unit's symbol (`kg`) and its name (`Kilogram`). */
  uomSymbol: string;
  uomName: string;
}

/** A unit choice that differs from the template's and needs confirming. */
export interface PendingUnitChoice {
  template: TemplateUnitPrompt;
  /** The unit the reader picked instead. */
  chosenUomId: string;
  chosenSymbol: string;
  chosenName: string;
}

interface UseUnitChoiceProps {
  /**
   * Whether this form creates a record. Only a create asks the catalogue: an
   * existing record already carries the unit it was saved with, and a form
   * that quietly moved it to the template's would be making the change the
   * confirmation exists for.
   */
  active: boolean;
  /** The product name and barcode the form is holding, for the lookup. */
  name: string | undefined;
  barcode: string | undefined;
  /** Fill the picker with a unit the catalogue settled on. */
  onAdoptTemplateUnit: (uomId: string) => void;
  /** Put a declined choice back the way the form has to keep it. */
  onRevertToTemplateUnit: (chosenUomId: string, templateUomId: string) => void;
}

/**
 * The unit the product is counted in, and the confirmation a different one owes.
 *
 * The server refuses a unit that contradicts the matched product template's
 * unless the request confirms the choice, so the form has to know the
 * template's unit *before* the save, and has to ask about a different one
 * while it can still name both. This hook is that knowledge: it asks the same
 * endpoint the create path resolves its template through, pre-fills the picker
 * once per matched product, and holds the question until the reader answers.
 */
export function useUnitChoice({
  active,
  name,
  barcode,
  onAdoptTemplateUnit,
  onRevertToTemplateUnit,
}: UseUnitChoiceProps) {
  const { data: uomCategories } = useUoms();
  const {
    hint,
    failed: unitLookupFailed,
    retry: retryUnitLookup,
  } = useTemplateUnitHint(
    active ? name : undefined,
    active ? barcode : undefined,
  );

  const templateUnit: TemplateUnitPrompt | null = useMemo(
    () =>
      hint
        ? {
            productName: hint.productName,
            uomSymbol: hint.uomSymbol,
            uomName: hint.uomName,
          }
        : null,
    [hint],
  );

  /**
   * The unit that was picked over the template's, waiting on the reader.
   *
   * The server refuses an unconfirmed difference, so the form asks here —
   * where it can still name both units and let the reader change their mind —
   * rather than letting the save come back as a refusal.
   */
  const [pendingUnitChoice, setPendingUnitChoice] =
    useState<PendingUnitChoice | null>(null);
  /** The unit the reader already confirmed standing in for the template's. */
  const [confirmedUomId, setConfirmedUomId] = useState<string | null>(null);

  /** The question a given unit owes, or `null` when it owes none. */
  const promptFor = useCallback(
    (uomId: string | undefined): PendingUnitChoice | null => {
      if (!hint || !templateUnit || !uomId || uomId === hint.uomId) return null;
      const chosen = findUom(uomCategories, uomId);
      // `findUom` answers with the catalogue's own record; without the
      // catalogue loaded there is nothing to confirm against, and the save
      // reads the choice the server-side way.
      if (!chosen) return null;
      return {
        template: templateUnit,
        chosenUomId: uomId,
        chosenSymbol: chosen.symbol,
        chosenName: chosen.name,
      };
    },
    [hint, templateUnit, uomCategories],
  );

  /**
   * Ask about a unit, if it differs from the template's.
   *
   * Called when the picker changes and again before a save, because the two
   * can disagree: a pre-fill landing after the change, a form that was
   * already holding a unit. Returns the question, so the caller can decide
   * whether to hold the save.
   */
  const askIfDifferent = useCallback(
    (uomId: string | undefined): PendingUnitChoice | null => {
      const prompt = promptFor(uomId);
      if (prompt) {
        setPendingUnitChoice(prompt);
        return prompt;
      }
      // The template's own unit (or none at all) is not a choice: whatever
      // was confirmed before is not this answer.
      setPendingUnitChoice(null);
      setConfirmedUomId(null);
      return null;
    },
    [promptFor],
  );

  /**
   * The reader's answer to "keep the unit this product is counted in, or enter
   * the quantity in the one you picked" — which the server converts back.
   *
   * Confirming records the choice, so the save carries the confirmation the
   * server requires and the record's history says who decided it. Declining
   * puts the template's unit back, because a form left holding a unit nobody
   * will save is a form that cannot be saved at all.
   */
  const resolveUnitChoice = useCallback(
    (confirmed: boolean) => {
      const prompt = pendingUnitChoice;
      setPendingUnitChoice(null);
      if (!prompt) return;
      if (confirmed) {
        setConfirmedUomId(prompt.chosenUomId);
        return;
      }
      setConfirmedUomId(null);
      if (hint) onRevertToTemplateUnit(prompt.chosenUomId, hint.uomId);
    },
    [pendingUnitChoice, hint, onRevertToTemplateUnit],
  );

  // A matched product pre-fills the picker with the unit it is counted in —
  // and only that unit: a reader who picks another one is asked to confirm
  // before anything is saved. Once per matched product, not once per render:
  // re-applying it would put the template's unit back over a choice the
  // reader has just made (and whose quantity was converted for it).
  const prefilledForTemplateRef = useRef<string | null>(null);
  useEffect(() => {
    if (!hint) {
      prefilledForTemplateRef.current = null;
      return;
    }
    if (prefilledForTemplateRef.current === hint.templateId) return;
    prefilledForTemplateRef.current = hint.templateId;
    onAdoptTemplateUnit(hint.uomId);
  }, [hint, onAdoptTemplateUnit]);

  // A different product is a different answer to "a quantity of what": a
  // choice confirmed for the previous one is not a choice about this one.
  useEffect(() => {
    setConfirmedUomId(null);
    setPendingUnitChoice(null);
  }, [hint?.templateId]);

  return {
    /**
     * The catalogue could not be asked which unit the product keeps, so
     * the question a different unit owes cannot be put yet.
     */
    unitLookupFailed,
    retryUnitLookup,
    /** The template's unit, when the catalogue knows the product. */
    templateUnit,
    /** Its id — what the save compares the form's unit against. */
    templateUomId: hint?.uomId ?? null,
    /** The chosen unit the template does not keep, waiting on the reader. */
    pendingUnitChoice,
    resolveUnitChoice,
    askIfDifferent,
    /**
     * Whether a unit is a deliberate choice at all — whether or not the
     * reader has confirmed it yet (the save asks when it has not).
     */
    isDifferentFromTemplate: (uomId: string | undefined): boolean =>
      Boolean(promptFor(uomId)),
    /**
     * Whether this save owes the server its confirmation flag: a different
     * unit, whose question the reader has already answered yes to.
     */
    isConfirmedChoice: (uomId: string | undefined): boolean =>
      Boolean(uomId) && Boolean(promptFor(uomId)) && uomId === confirmedUomId,
  };
}
