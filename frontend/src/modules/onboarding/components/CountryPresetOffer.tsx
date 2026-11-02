import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Checkbox } from "@/components/ui/Checkbox";
import { countryLabel } from "@/module-sdk";
import type { ProductProfile } from "@/types";
import { useCountryPreset } from "../hooks/useOnboarding";

interface OfferContext {
  country: string;
  step: "profile" | "modules" | "focus";
  /** What the reader ticked on the module step. */
  modules: string[];
  profile: ProductProfile | null;
  isModuleMode: boolean;
}

/**
 * Whether the country's document preset is on offer, and the answer to it.
 *
 * The offer is made where it can be kept: the organization will run the
 * warehouse module and its country has a preset. A mode with a second step
 * shows it on the step that settles the module set; one without shows it at
 * once. The country's paperwork is offered, not assumed — it sits on top of
 * the working style the mode brings.
 */
export function useCountryPresetOffer({
  country,
  step,
  modules,
  profile,
  isModuleMode,
}: OfferContext) {
  const [accepted, setAccepted] = useState(true);
  const { data: preset } = useCountryPreset(country);
  const runsWarehouse =
    step === "modules"
      ? modules.includes("warehouse")
      : step === "profile" &&
        !isModuleMode &&
        (profile?.default_modules ?? []).includes("warehouse") &&
        (profile?.suggested_modules ?? []).length === 0;
  const offered = Boolean(preset) && runsWarehouse;
  return {
    offered,
    accepted,
    setAccepted,
    /** What setup sends: nothing at all when no offer was made. */
    answer: offered ? accepted : undefined,
  };
}

export function CountryPresetOffer({
  country,
  offer,
}: {
  country: string;
  offer: ReturnType<typeof useCountryPresetOffer>;
}) {
  const { t, i18n } = useTranslation("onboarding");
  if (!offer.offered) return null;
  return (
    <label
      htmlFor="onboarding-country-preset"
      className="mt-6 flex w-full max-w-2xl cursor-pointer items-start gap-3"
    >
      <Checkbox
        id="onboarding-country-preset"
        className="mt-0.5 shrink-0"
        checked={offer.accepted}
        onChange={(e) => offer.setAccepted(e.target.checked)}
      />
      <span className="min-w-0">
        <span className="block text-sm text-on">
          {t("countryPresetLabel", {
            country: countryLabel(country, i18n.language),
          })}
        </span>
        <span className="block text-xs text-on-muted">
          {t("countryPresetHint")}
        </span>
      </span>
    </label>
  );
}
