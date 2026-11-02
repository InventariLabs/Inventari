import { useEffect, useRef, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import axios from "axios";
import { useQueryClient } from "@tanstack/react-query";
import { PackageSearch, ShieldAlert } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { NativeSelect } from "@/components/ui/NativeSelect";
import LoadingSpinner from "@/components/LoadingSpinner";
import { QueryFailure } from "@/components/ui/QueryResult";
import { LanguageSelector } from "@/components/LanguageSelector";
import {
  CURRENCY_BY_COUNTRY,
  CURRENCY_CODES,
  currencyLabel,
} from "@/lib/currencies";
import { queryKeys } from "@/hooks/queries/keys";
import { COUNTRY_CODES, countryFromLocale, countryLabel } from "@/module-sdk";
import { resolveModuleTarget, moduleRegistry } from "@/lib/moduleRegistry";
import { useMyModules } from "@/modules/settings/hooks/useModules";
import { useOrganization } from "@/modules/settings/hooks/useOrganization";
import { useAuthStore } from "@/store/authStore";
import type { Organization, ProductProfile, User } from "@/types";
import { useProfiles, useOnboardingSetup } from "../hooks/useOnboarding";
import {
  CountryPresetOffer,
  useCountryPresetOffer,
} from "../components/CountryPresetOffer";
import { ModuleChoiceStep } from "../components/ModuleChoiceStep";
import {
  OrganizationNameField,
  useOrganizationName,
} from "../components/OrganizationNameField";
import { FocusModuleStep } from "../components/FocusModuleStep";
import { ModeCards, CHOSEN_MODULE } from "../components/ModeCards";

// The neutral profile the one-module choice sits on.
const BASE_PROFILE = "clean_core";

/**
 * The currency and country this interface language is most likely to belong
 * to — one table, so the two answers cannot disagree: a Polish interface on
 * an en-US browser used to offer PLN with the United States selected.
 *
 * The screen used to open on USD whatever the language, and the currency is
 * permanent for the organization — a Polish first-run picked dollars unless
 * the reader noticed a select at the bottom of the page.
 *
 * Guessing from the language is only fair while the language is a choice the
 * reader can make here, which is why this screen now carries the language
 * selector: the first administrator of an installation is created with
 * `preferred_language='en'` and had no way to say otherwise before signing in
 * for a second time.
 */
const COUNTRY_BY_LANGUAGE: Record<string, string> = {
  pl: "PL",
  de: "DE",
  fr: "FR",
  es: "ES",
  "en-GB": "GB",
};

/** The typed table, read by a code that may be empty or unlisted. */
const currencyByCountry: Readonly<Record<string, string>> = CURRENCY_BY_COUNTRY;

/**
 * One guess, country first: the language names its country, a language the
 * table does not know (English, Portuguese) asks the browser's locale, and the
 * currency follows whichever country that gave. An English interface on a
 * de-DE browser therefore reads DE with EUR, not DE with dollars.
 */
function languageDefaults(language: string): {
  currency: string;
  country: string;
} {
  const country =
    COUNTRY_BY_LANGUAGE[language] ??
    COUNTRY_BY_LANGUAGE[language.split("-")[0]] ??
    countryFromLocale(navigator.language) ??
    "";
  return {
    country,
    currency: currencyByCountry[country] ?? "USD",
  };
}

function defaultCurrency(language: string): string {
  return languageDefaults(language).currency;
}

function defaultCountry(language: string): string {
  return languageDefaults(language).country;
}

/**
 * The currency and country selects, opened on the language's guess. The guess
 * follows the language until the reader overrules that select: switching to
 * Polish and leaving dollars selected would make the language selector look
 * like it had missed the point. The country picks the tax rate and the
 * partner rule the documents follow; "not set" stays an answer.
 */
function useLanguageDefaults(languageInUse: string) {
  const language = languageInUse || "en";
  const [currency, setCurrencyState] = useState(() =>
    defaultCurrency(language),
  );
  const [country, setCountryState] = useState(() => defaultCountry(language));
  const currencyChosen = useRef(false);
  const countryChosen = useRef(false);
  useEffect(() => {
    if (!currencyChosen.current) setCurrencyState(defaultCurrency(language));
    if (!countryChosen.current) setCountryState(defaultCountry(language));
  }, [language]);
  return {
    currency,
    country,
    setCurrency: (value: string) => {
      currencyChosen.current = true;
      setCurrencyState(value);
    },
    setCountry: (value: string) => {
      countryChosen.current = true;
      setCountryState(value);
    },
  };
}

/** What the current step still lacks before it can go on. */
function isIncomplete(
  step: "profile" | "modules" | "focus",
  nameBlank: boolean,
  focusModule: string | null,
): boolean {
  return nameBlank || (step === "focus" && !focusModule);
}

const STEP_COPY = {
  profile: { title: "profileSelectTitle", subtitle: "profileSelectSubtitle" },
  modules: { title: "moduleChoiceTitle", subtitle: "moduleChoiceSubtitle" },
  focus: { title: "focusChoiceTitle", subtitle: "focusChoiceSubtitle" },
} as const;

/**
 * The home of the module the organization just focused on.
 *
 * The router is rebuilt when the enabled set changes, and the new one starts
 * from the address the page had at that moment: a client-side navigate from
 * here lands on the new URL while the rebuilt router still renders this
 * screen. The one-module choice therefore leaves by a full load, which boots
 * straight into the narrowed workspace behind the shell's own spinner — the
 * launcher of the other modules is never drawn.
 */
function focusHome(focusModule: string): string {
  const focused = moduleRegistry.getModule(focusModule);
  return focused ? resolveModuleTarget(focused) : "/";
}

/**
 * Why this screen has nothing to offer the reader, if it does not.
 *
 * "done": the organization finished setup (null reads as finished, as in
 * OnboardingGuard), so there is nothing to choose and a submit would only be
 * refused with a 409. Our own submit flips the flag under us, hence
 * `submitting` — the screen's own way out must not be pre-empted.
 *
 * "not-admin": setting up is admin-only; saying so up front beats offering a
 * wizard that can only end in the 403. An unknown user (not loaded yet) is let
 * through — the server still decides.
 */
function whyClosed(
  org: Organization | undefined,
  user: User | null,
  submitting: boolean,
): "done" | "not-admin" | null {
  if (org && org.onboarding_completed !== false && !submitting) return "done";
  if (user && user.role !== "admin" && !user.is_superuser) return "not-admin";
  return null;
}

/**
 * The first choice. A failed profile list is said so: the grid of an empty
 * array held only the one-module card, as if it were the whole offer.
 */
function ModeChoice({
  profiles,
  error,
  onRetry,
  selected,
  onSelect,
}: {
  profiles: ProductProfile[] | undefined;
  error: unknown;
  onRetry: () => void;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  if (error) return <QueryFailure error={error} onRetry={onRetry} />;
  return (
    <ModeCards
      profiles={profiles ?? []}
      selected={selected}
      onSelect={onSelect}
    />
  );
}

/** The account may not set this up, or the server just said so. */
function ForbiddenScreen({ onSignOut }: { onSignOut: () => void }) {
  const { t } = useTranslation("onboarding");
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-surface p-4 sm:p-8">
      <div className="max-w-md space-y-4 text-center">
        <ShieldAlert size={32} className="mx-auto text-amber-600" />
        <h1 className="text-xl font-semibold text-on tracking-tight">
          {t("forbiddenTitle")}
        </h1>
        <p className="text-sm text-on-secondary">{t("forbiddenBody")}</p>
        <Button variant="outline" onClick={onSignOut}>
          {t("signOut")}
        </Button>
      </div>
    </div>
  );
}

/**
 * What the first screen cannot be offered without: the profiles to choose
 * from, and the modules already switched on (the second step ticks from
 * them, and setup takes the list as the whole answer). Either failing is a
 * failure of the screen, not an empty list.
 */
function useSetupLookups() {
  const profilesQuery = useProfiles();
  const modulesQuery = useMyModules();
  const failed = profilesQuery.isError ? profilesQuery : modulesQuery;
  return {
    profiles: profilesQuery.data,
    isLoading: profilesQuery.isLoading,
    enabledModules: modulesQuery.data,
    lookupError: failed.isError ? failed.error : null,
    retryLookups: () => {
      if (profilesQuery.isError) void profilesQuery.refetch();
      if (modulesQuery.isError) void modulesQuery.refetch();
    },
  };
}

export default function OnboardingPage() {
  const { t, i18n } = useTranslation("onboarding");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const logout = useAuthStore((state) => state.logout);
  const user = useAuthStore((state) => state.user);
  const [selectedProfile, setSelectedProfile] = useState<string | null>(null);
  // The two steps: which kind of place this is, then what it starts with.
  const [step, setStep] = useState<"profile" | "modules" | "focus">("profile");
  const [focusModule, setFocusModule] = useState<string | null>(null);
  const [modules, setModules] = useState<string[]>([]);
  const { currency, setCurrency, country, setCountry } = useLanguageDefaults(
    i18n.language,
  );
  const [forbidden, setForbidden] = useState(false);

  const { data: org, isLoading: orgLoading } = useOrganization();
  const {
    name: nameShown,
    setName: setOrganizationName,
    answer: organizationName,
    blank: nameBlank,
  } = useOrganizationName(org?.name);
  const { profiles, isLoading, enabledModules, lookupError, retryLookups } =
    useSetupLookups();
  const { mutateAsync: setupProfileAsync, isPending } = useOnboardingSetup();
  // True from the first submit until it fails; see `whyClosed`.
  const settingUp = useRef(false);

  async function handleConfirm() {
    if (!selectedProfile) return;
    if (isModuleMode && !focusModule) return;
    settingUp.current = true;
    try {
      await setupProfileAsync({
        profileId: isModuleMode ? BASE_PROFILE : selectedProfile,
        focusModule: isModuleMode ? (focusModule ?? undefined) : undefined,
        currency,
        country: country || undefined,
        useCountryPreset: countryOffer.answer,
        organizationName,
        // Only a step the reader actually saw can speak for them. Sending the
        // untouched `[]` from a skipped step would read as "they unticked
        // everything" and leave the organization with the pinned modules
        // alone.
        modules: step === "modules" ? modules : undefined,
      });
      // await the refetch (invalidate is non-blocking) so
      // OnboardingGuard sees the refreshed onboarding_completed=true before
      // we navigate — otherwise it bounces the user back to /onboarding.
      await queryClient.refetchQueries({
        queryKey: queryKeys.organization.detail,
      });
      toast.success(t("profileApplied"));
      if (isModuleMode && focusModule) {
        window.location.replace(focusHome(focusModule));
        return;
      }
      navigate("/", { replace: true });
    } catch (error) {
      settingUp.current = false;
      // A 403 is not a retry: this account will never be allowed to apply a
      // profile, and "please try again" leaves it circling the one screen it
      // cannot leave. Say what is wrong and offer the way out.
      if (axios.isAxiosError(error) && error.response?.status === 403) {
        setForbidden(true);
        return;
      }
      toast.error(t("profileError"));
    }
  }

  const isModuleMode = selectedProfile === CHOSEN_MODULE;
  const activeProfile =
    (profiles ?? []).find((p) => p.id === selectedProfile) ?? null;
  const countryOffer = useCountryPresetOffer({
    country,
    step,
    modules,
    profile: activeProfile,
    isModuleMode,
  });

  // A mode that offers nothing has no second step. That is the household
  // answer: someone who came to know what is in the fridge and what they can
  // cook gets a working application without a single question about modules.
  // A business is the opposite case — "business" is a document ledger, IT
  // equipment, a ski rental and livestock, and no preset covers that, so the
  // choice is the only honest answer.
  const hasOffer =
    isModuleMode || (activeProfile?.suggested_modules ?? []).length > 0;

  function handleContinue() {
    if (isModuleMode) {
      setStep("focus");
      return;
    }
    if (!activeProfile) return;
    // The mode's own list is the starting tick. From here the reader adds
    // what no profile enables, or drops what their kind of place does not
    // need — safe now, on an empty organization, in a way it never is later.
    //
    // A module the organization already switched on is ticked too: setup
    // takes the list as the whole answer, so a box that reads unticked for
    // something already running switches it off on "Get started". A fresh
    // organization holds only the always-on modules, which this step never
    // offers, so for it the union adds nothing.
    const offered = new Set([
      ...activeProfile.default_modules,
      ...(activeProfile.suggested_modules ?? []),
    ]);
    const alreadyOn = (enabledModules ?? []).filter((name) =>
      offered.has(name),
    );
    setModules([...new Set([...activeProfile.default_modules, ...alreadyOn])]);
    setStep("modules");
  }

  function toggleModule(name: string) {
    setModules((current) =>
      current.includes(name)
        ? current.filter((m) => m !== name)
        : [...current, name],
    );
  }

  const closed = whyClosed(org, user, settingUp.current);
  if (closed === "done") return <Navigate to="/" replace />;

  if (forbidden || closed === "not-admin") {
    return <ForbiddenScreen onSignOut={() => void logout()} />;
  }

  // `pt-16` reserves the floating strip's own height: the page is taller
  // than a phone, so there it starts at the top of the viewport and the strip
  // sat on the wordmark.
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-surface p-4 pt-16 sm:p-8">
      {/* The two ways off this screen. Without them the only exit from a
          first run started on the wrong account, or in the wrong language,
          was to clear the session cookie by hand. */}
      <div className="fixed top-4 right-4 flex items-center gap-1">
        <LanguageSelector align="right" />{" "}
        <Button
          className="min-h-11 md:min-h-0 min-w-11 md:min-w-0"
          variant="ghost"
          size="contentSm"
          onClick={() => void logout()}
        >
          {t("signOut")}
        </Button>
      </div>

      {/* Header */}
      <div className="mb-10 text-center max-w-md">
        <div className="flex items-center justify-center gap-2 mb-4">
          <PackageSearch size={32} className="text-primary-600" />
          <span className="text-xl font-semibold text-on tracking-tight">
            Inventari
          </span>
        </div>
        <h1 className="text-xl font-semibold text-on tracking-tight">
          {t(STEP_COPY[step].title)}
        </h1>
        <p className="text-sm text-on-secondary">
          {t(STEP_COPY[step].subtitle)}
        </p>
      </div>

      {/* Profile cards */}
      {step === "focus" ? (
        <FocusModuleStep selected={focusModule} onSelect={setFocusModule} />
      ) : step === "modules" && activeProfile ? (
        <ModuleChoiceStep
          profile={activeProfile}
          selected={modules}
          onToggle={toggleModule}
        />
      ) : isLoading || orgLoading ? (
        <LoadingSpinner />
      ) : (
        <ModeChoice
          profiles={profiles}
          error={lookupError}
          onRetry={retryLookups}
          selected={selectedProfile}
          onSelect={setSelectedProfile}
        />
      )}

      <OrganizationNameField
        visible={step === "profile"}
        value={nameShown}
        onChange={setOrganizationName}
        blank={nameBlank}
      />

      <CountryPresetOffer country={country} offer={countryOffer} />

      {/* Fleet valuation and every price sum in this currency. */}
      <div className="mt-6 w-full max-w-2xl flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        {/* The hint and its 192 px select stood side by side with the actions
            on every width; on a phone the three together ran off the screen.
            Stacked below `sm`, hidden there once the choice is made — an
            invisible block still holds its space, which on a phone is a gap
            with nothing in it. */}
        <div
          className={cn(
            // One grid for both answers: the two hints differ in length, and
            // separate rows left their selects ending at different edges.
            "grid gap-2 sm:grid-cols-[auto_18rem] sm:items-center sm:gap-x-2 sm:gap-y-4",
            step !== "profile" && "hidden sm:invisible sm:grid",
          )}
        >
          <div>
            <label
              htmlFor="onboarding-currency"
              className="block text-sm text-on-secondary"
            >
              {t("currencyLabel")}
            </label>
            <p className="text-xs text-on-muted">{t("currencyHint")}</p>
          </div>
          {/* The same list the rest of the application offers. Four options
              here meant an organization settling in Swiss francs had to pick
              a currency that was not theirs and correct it later. */}
          <NativeSelect
            wrapperClassName="w-full"
            id="onboarding-currency"
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
          >
            {CURRENCY_CODES.map((code) => (
              <option key={code} value={code}>
                {code} — {currencyLabel(code, i18n.language)}
              </option>
            ))}
          </NativeSelect>
          <div className="mt-2 sm:mt-0">
            <label
              htmlFor="onboarding-country"
              className="block text-sm text-on-secondary"
            >
              {t("countryLabel")}
            </label>
            <p className="text-xs text-on-muted">{t("countryHint")}</p>
          </div>
          <NativeSelect
            wrapperClassName="w-full"
            id="onboarding-country"
            value={country}
            onChange={(e) => setCountry(e.target.value)}
          >
            <option value="">{t("countryNone")}</option>
            {COUNTRY_CODES.map((code) => (
              <option key={code} value={code}>
                {code} — {countryLabel(code, i18n.language)}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="flex w-full items-center gap-2 sm:w-auto">
          {step !== "profile" && (
            <Button
              variant="ghost"
              onClick={() => setStep("profile")}
              disabled={isPending}
            >
              {t("back")}
            </Button>
          )}
          <Button
            onClick={
              step === "profile" && hasOffer ? handleContinue : handleConfirm
            }
            disabled={
              !selectedProfile ||
              isPending ||
              isIncomplete(step, nameBlank, focusModule)
            }
            className="w-full min-w-[140px] sm:w-auto"
          >
            {isPending ? (
              <span className="flex items-center gap-2">
                <span className="h-4 w-4 animate-spin rounded-full border border-white border-t-transparent" />
                {t("profileApplying")}
              </span>
            ) : step === "profile" && hasOffer ? (
              t("continue")
            ) : (
              t("startWithProfile")
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}
