import { useTranslation } from "react-i18next";
import type { StorageLocationSummary } from "@/types";
import { useActiveProfile } from "@/module-sdk";

/**
 * Profile-aware name suggestions for a new location: the chips the storage
 * wizard's two naming steps offer, and the ones the "new location" sheet the
 * pickers open offers beside its name field.
 */
export function useWizardSuggestions(
  existingLocations: StorageLocationSummary[],
  selectedParent: StorageLocationSummary | undefined,
) {
  const { t } = useTranslation(["locations"]);
  const activeProfile = useActiveProfile();
  const profileKey = activeProfile?.seed_profile ?? null;
  const readSuggestions = (
    kind: "zones" | "locations" | "compartments",
  ): string[] => {
    if (profileKey) {
      const profileValue = t(`suggestions.profiles.${profileKey}.${kind}`, {
        returnObjects: true,
      });
      if (Array.isArray(profileValue)) return profileValue as string[];
    }
    const generic = t(`suggestions.${kind}`, { returnObjects: true });
    return Array.isArray(generic) ? (generic as string[]) : [];
  };
  const parentSuggestions: string[] = readSuggestions("zones");
  // What step 2 offers follows where the new row will stand, one rule for
  // every profile: inside an appliance — a fridge, a freezer, read by the
  // type's code, never by its translated name — or under anything that is
  // not a root, the chips name compartments (shelves, drawers, bins);
  // a root, or a zone the first step has just typed, gets the places
  // themselves: appliances and furniture.
  const parentTypeCode = selectedParent?.location_type?.type_code ?? null;
  const insideAnAppliance =
    parentTypeCode === "FRIDGE" || parentTypeCode === "FREEZER";
  const underANonRoot = selectedParent?.parent_id != null;
  const locationSuggestions: string[] = readSuggestions(
    insideAnAppliance || underANonRoot ? "compartments" : "locations",
  );
  // A name the organization already uses is not a suggestion for a new one.
  const existingParentNames = new Set(
    existingLocations.map((z) => z.name.toLowerCase()),
  );
  const filteredParentSuggestions = parentSuggestions.filter(
    (s) => !existingParentNames.has(s.toLowerCase()),
  );
  // A sibling already carrying the name is not a suggestion either: under a
  // "Freezer Zone" holding "Freezer 1" and "Freezer 2", the chip that would
  // add a third one is noise.
  const existingChildNames = new Set(
    selectedParent
      ? existingLocations
          .filter((s) => s.parent_id === selectedParent.id)
          .map((s) => s.name.toLowerCase())
      : [],
  );
  const filteredLocationSuggestions = locationSuggestions.filter(
    (s) => !existingChildNames.has(s.toLowerCase()),
  );
  return {
    parentSuggestions,
    locationSuggestions: filteredLocationSuggestions,
    filteredParentSuggestions,
  };
}

/**
 * The name field after a chip is tapped. A chip fills an empty field, swaps
 * one chip for another and completes a half-typed word, but it never throws
 * away a name that was typed: "Rack A" stays when "Rack" is tapped.
 */
export function nameAfterChip(
  typed: string,
  chip: string,
  suggestions: readonly string[],
): string {
  const current = typed.trim().toLowerCase();
  const replaceable =
    current === "" ||
    chip.toLowerCase().startsWith(current) ||
    suggestions.some((s) => s.toLowerCase() === current);
  return replaceable ? chip : typed;
}
