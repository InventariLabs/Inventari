import { useState, useEffect, useRef, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Building2, Users, UsersRound, Settings } from "lucide-react";
import Button from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { useFormGuard } from "@/hooks/useFormGuard";
import { CURRENCY_CODES, currencyLabel } from "@/lib/currencies";
import { COUNTRY_CODES, countryLabel } from "@/lib/countries";
import { TIMEZONE_CODES, timezoneLabel } from "@/lib/timezones";
import { extractApiError } from "@/lib/errors";
import InvitationsSection from "./InvitationsSection";
import OrganizationMembers from "./OrganizationMembers";
import RegistrationRequestsSection from "./RegistrationRequestsSection";
import { useHasPermission } from "@/hooks/useHasPermission";
import { useAuthStore } from "@/store/authStore";
import { toast } from "sonner";
import {
  useOrganization,
  useUpdateOrganization,
  useUploadOrganizationLogo,
  useDeleteOrganizationLogo,
} from "@/modules/settings/hooks/useOrganization";

export default function OrganizationSettings() {
  const { t } = useTranslation("common");

  // One gate for the whole page. The store keeps a single slot, and two
  // cards on this screen can hold unsaved work at once — so the cards
  // report their dirtiness here instead of arming the guard themselves,
  // where the first card going clean would silently disarm the question
  // the second card's unsaved fields still need asked.
  const [dirtyCards, setDirtyCards] = useState({ org: false, issuer: false });
  const reportOrgDirty = useCallback(
    (value: boolean) =>
      setDirtyCards((prev) =>
        prev.org === value ? prev : { ...prev, org: value },
      ),
    [],
  );
  const reportIssuerDirty = useCallback(
    (value: boolean) =>
      setDirtyCards((prev) =>
        prev.issuer === value ? prev : { ...prev, issuer: value },
      ),
    [],
  );

  useFormGuard(
    dirtyCards.org || dirtyCards.issuer,
    t("settings.organization.guardName", "The organization settings"),
  );

  // Both cards seed their forms with defaults until the organization
  // arrives; a failed read must not leave those on screen as if saved, nor
  // offer a Save that would write them over the stored values.
  // Until it has been read, nothing editable shows — including while Try
  // again is in flight, when the query is pending rather than in error.
  const {
    data: org,
    isError,
    errorUpdateCount,
    isFetching,
    refetch,
  } = useOrganization();
  // `isError` drops back to pending while Try again is in flight; the count
  // remembers that the read failed.
  const failed = isError || errorUpdateCount > 0;

  return (
    <div className="space-y-6">
      {!org ? (
        failed ? (
          <Card className="p-0 overflow-hidden sm:rounded-xl rounded-none">
            <EmptyState
              icon={Settings}
              title={t("settings.organization.loadFailed")}
              description={t("settings.organization.loadFailedHint")}
              primaryAction={
                <Button
                  variant="outline"
                  isLoading={isFetching}
                  onClick={() => refetch()}
                >
                  {t("actions.retry")}
                </Button>
              }
            />
          </Card>
        ) : null
      ) : (
        <>
          <OrganizationCard onDirtyChange={reportOrgDirty} />
          <IssuerCard org={org} onDirtyChange={reportIssuerDirty} />
        </>
      )}
      <PeopleCard />
    </div>
  );
}

type LoadedOrg = NonNullable<ReturnType<typeof useOrganization>["data"]>;

const currencyOf = (org?: LoadedOrg) => org?.currency ?? "USD";
const timezoneOf = (org?: LoadedOrg) => org?.timezone ?? "UTC";

/** The issuer block as the form holds it. The wire types the address a loose
 * dict; the form reads exactly its three members, so they are narrowed once,
 * here. */
function issuerFormOf(org?: LoadedOrg) {
  const address = (org?.address ?? {}) as {
    street?: string | null;
    city?: string | null;
    postal_code?: string | null;
  };
  return {
    taxId: org?.tax_id ?? "",
    country: org?.country ?? "",
    street: address.street ?? "",
    city: address.city ?? "",
    postalCode: address.postal_code ?? "",
    logoUrl: org?.logo_url ?? null,
  };
}

/** The organization itself: what it is called and what it counts money in. */
function OrganizationCard({
  onDirtyChange,
}: {
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { t, i18n } = useTranslation("common");
  const isAdmin = useHasPermission("admin:access");

  // Queries
  const { data: household } = useOrganization();

  // The card mounts only once the organization has been read, so the forms
  // start from the stored values rather than from a first dirty render.
  const [orgName, setOrgName] = useState(household?.name ?? "");
  const [selectedCurrency, setSelectedCurrency] = useState(
    currencyOf(household),
  );
  const [selectedTimezone, setSelectedTimezone] = useState(
    timezoneOf(household),
  );

  useEffect(() => {
    if (household) {
      setOrgName(household.name);
      setSelectedCurrency(currencyOf(household));
      setSelectedTimezone(timezoneOf(household));
    }
  }, [household]);

  // Mutations
  const updateOrgMutation = useUpdateOrganization();

  const savedCurrency =
    household?.settings?.currency ?? household?.currency ?? "USD";
  const currencyChanged = selectedCurrency !== savedCurrency;
  const timezoneChanged = selectedTimezone !== timezoneOf(household);
  const isDirty =
    orgName !== (household?.name ?? "") || currencyChanged || timezoneChanged;

  // The page's gate asks about this card's unsaved work on the way out; the
  // report, not the local flag, is what reaches it.
  useEffect(() => {
    onDirtyChange(isDirty);
    return () => onDirtyChange(false);
  }, [isDirty, onDirtyChange]);

  const handleSaveConfig = () => {
    updateOrgMutation.mutate(
      { name: orgName, currency: selectedCurrency, timezone: selectedTimezone },
      {
        onSuccess: () => toast.success(t("settings.organization.saved")),
        onError: (err: unknown) =>
          toast.error(extractApiError(err, t("messages.error"))),
      },
    );
  };

  return (
    <Card className="p-0 overflow-hidden sm:rounded-xl rounded-none">
      {/* Org identity row */}
      <div className="flex items-center gap-3 px-4 py-3.5 border-b border-border">
        <div className="w-9 h-9 rounded-xl flex items-center justify-center bg-primary-50 text-primary-700 dark:bg-primary-500/10 dark:text-primary-500 shrink-0">
          <Users size={17} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-on truncate leading-tight">
            {household?.name ?? "—"}
          </p>
          {household?.short_id && (
            <p className="text-xs text-on-muted font-mono truncate">
              {household.short_id}
            </p>
          )}
        </div>
      </div>

      {/* Organization config — single save */}
      {isAdmin && (
        <div className="px-4 py-3.5 space-y-3">
          <div className="space-y-1.5">
            <Input
              label={t("settings.organization.orgName", {
                defaultValue: "Organization name",
              })}
              value={orgName}
              onChange={(e) => setOrgName(e.target.value)}
            />
          </div>

          <div className="space-y-1.5">
            {/* One currency list for the whole application — this screen
                used to offer ten while the first-run screen offered four
                and the purchase-order forms offered twenty-nine. */}
            <NativeSelect
              label={t("settings.organization.currency", {
                defaultValue: "Currency",
              })}
              value={selectedCurrency}
              onChange={(e) => setSelectedCurrency(e.target.value)}
            >
              {CURRENCY_CODES.map((code) => (
                <option key={code} value={code}>
                  {code} — {currencyLabel(code, i18n.language)}
                </option>
              ))}
            </NativeSelect>
            {currencyChanged && (
              <p className="text-xs text-amber-700 dark:text-amber-400">
                {t("settings.organization.currencyChangeWarning")}
              </p>
            )}
          </div>

          <div className="space-y-1.5">
            {/* The organization's own clock — the day expiry buckets,
                inventory periods and reports cut on. The stored zone is
                offered even when it is not on the curated list. */}
            <NativeSelect
              label={t("settings.organization.timezone", {
                defaultValue: "Timezone",
              })}
              value={selectedTimezone}
              onChange={(e) => setSelectedTimezone(e.target.value)}
            >
              {(TIMEZONE_CODES.includes(
                selectedTimezone as (typeof TIMEZONE_CODES)[number],
              )
                ? TIMEZONE_CODES
                : [selectedTimezone, ...TIMEZONE_CODES]
              ).map((zone) => (
                <option key={zone} value={zone}>
                  {timezoneLabel(zone)}
                </option>
              ))}
            </NativeSelect>
            <p className="text-xs text-on-muted">
              {t("settings.organization.timezoneHint")}
            </p>
          </div>

          <div className="flex justify-end pt-1">
            <Button
              onClick={handleSaveConfig}
              disabled={!isDirty || updateOrgMutation.isPending}
              isLoading={updateOrgMutation.isPending}
            >
              {t("actions.save")}
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}

/** The document issuer: name, tax ID, country, address and logo printed on
 * warehouse document PDFs. Lives on the organization — one identity
 * for every print family — so a document printout can circulate outside the
 * app in any country.
 */
function IssuerCard({
  org,
  onDirtyChange,
}: {
  org: LoadedOrg;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { t, i18n } = useTranslation("common");
  const isAdmin = useHasPermission("admin:access");

  const updateOrgMutation = useUpdateOrganization();
  const uploadLogoMutation = useUploadOrganizationLogo();
  const deleteLogoMutation = useDeleteOrganizationLogo();

  const saved = issuerFormOf(org);
  const [taxId, setTaxId] = useState(saved.taxId);
  const [country, setCountry] = useState(saved.country);
  const [street, setStreet] = useState(saved.street);
  const [city, setCity] = useState(saved.city);
  const [postalCode, setPostalCode] = useState(saved.postalCode);
  const [logoUrl, setLogoUrl] = useState<string | null>(saved.logoUrl);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!org) return;
    const form = issuerFormOf(org);
    setTaxId(form.taxId);
    setCountry(form.country);
    setStreet(form.street);
    setCity(form.city);
    setPostalCode(form.postalCode);
    setLogoUrl(form.logoUrl);
  }, [org]);

  const isDirty =
    taxId !== saved.taxId ||
    country !== saved.country ||
    street !== saved.street ||
    city !== saved.city ||
    postalCode !== saved.postalCode;

  useEffect(() => {
    onDirtyChange(isDirty);
    return () => onDirtyChange(false);
  }, [isDirty, onDirtyChange]);

  const handleSaveConfig = () => {
    updateOrgMutation.mutate(
      {
        tax_id: taxId || null,
        country: country || null,
        address: {
          street: street || null,
          city: city || null,
          postal_code: postalCode || null,
        },
      },
      {
        onSuccess: () => toast.success(t("settings.organization.issuerSaved")),
        onError: (err: unknown) =>
          toast.error(extractApiError(err, t("messages.error"))),
      },
    );
  };

  const handleLogoFile = (file: File | undefined) => {
    if (!file) return;
    uploadLogoMutation.mutate(file, {
      onSuccess: (result) => {
        setLogoUrl(result.logo_url);
        toast.success(t("messages.success"));
      },
      // The server names the refusal — the file is not an image, the image is
      // over the ceiling — in the language the request asked for.
      onError: (err: unknown) =>
        toast.error(extractApiError(err, t("messages.error"))),
    });
  };

  const handleRemoveLogo = () => {
    deleteLogoMutation.mutate(undefined, {
      onSuccess: () => {
        setLogoUrl(null);
        toast.success(t("messages.success"));
      },
      onError: (err: unknown) =>
        toast.error(extractApiError(err, t("messages.error"))),
    });
  };

  return (
    <Card className="p-0 overflow-hidden sm:rounded-xl rounded-none">
      <div className="flex items-center gap-3 px-4 py-3.5 border-b border-border">
        <div className="w-9 h-9 rounded-xl flex items-center justify-center bg-primary-50 text-primary-700 dark:bg-primary-500/10 dark:text-primary-500 shrink-0">
          <Building2 size={17} />
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-on leading-tight">
            {t("settings.organization.issuerTitle", "Document issuer")}
          </h2>
          <p className="text-xs text-on-muted mt-0.5">
            {t(
              "settings.organization.issuerHint",
              "Printed on document printouts — name, tax ID, address and logo of the issuing organization.",
            )}
          </p>
        </div>
      </div>

      {isAdmin && (
        <div className="px-4 py-3.5 space-y-3">
          <div className="grid grid-cols-1 items-end sm:grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Input
                label={t("settings.organization.taxId", "Tax ID (VAT/NIP)")}
                value={taxId}
                onChange={(e) => setTaxId(e.target.value)}
                maxLength={50}
              />
            </div>

            <div className="space-y-1.5">
              <NativeSelect
                label={t("settings.organization.country", "Country")}
                value={country}
                onChange={(e) => setCountry(e.target.value)}
              >
                <option value="">
                  {t("settings.organization.countryNone", "Not set")}
                </option>
                {COUNTRY_CODES.map((code) => (
                  <option key={code} value={code}>
                    {code} — {countryLabel(code, i18n.language)}
                  </option>
                ))}
              </NativeSelect>
            </div>

            <div className="space-y-1.5">
              <Input
                label={t("settings.organization.street", "Street")}
                value={street}
                onChange={(e) => setStreet(e.target.value)}
                maxLength={255}
              />
            </div>

            <div className="space-y-1.5">
              <Input
                label={t("settings.organization.city", "City")}
                value={city}
                onChange={(e) => setCity(e.target.value)}
                maxLength={255}
              />
            </div>

            <div className="space-y-1.5">
              <Input
                label={t("settings.organization.postalCode", "Postal code")}
                value={postalCode}
                onChange={(e) => setPostalCode(e.target.value)}
                maxLength={20}
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <p className="block text-xs font-medium text-on-muted">
              {t("settings.organization.logo", "Logo")}
            </p>
            {logoUrl ? (
              <div className="flex items-center gap-3">
                <img
                  src={`/uploads/${logoUrl}`}
                  alt={t("settings.organization.logo", "Logo")}
                  className="h-12 w-auto rounded border border-border bg-white object-contain"
                />
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleRemoveLogo}
                  isLoading={deleteLogoMutation.isPending}
                >
                  {t("settings.organization.logoRemove", "Remove logo")}
                </Button>
              </div>
            ) : (
              <>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/gif,image/webp"
                  className="hidden"
                  onChange={(e) => {
                    handleLogoFile(e.target.files?.[0]);
                    e.target.value = "";
                  }}
                />
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => fileInputRef.current?.click()}
                  isLoading={uploadLogoMutation.isPending}
                >
                  {t("settings.organization.logoUpload", "Upload logo")}
                </Button>
              </>
            )}
            <p className="text-xs text-on-muted">
              {t(
                "settings.organization.logoHint",
                "PNG, JPG, GIF or WebP up to 5 MB. Shown on printed documents.",
              )}
            </p>
          </div>

          <div className="flex justify-end pt-1">
            <Button
              onClick={handleSaveConfig}
              disabled={!isDirty || updateOrgMutation.isPending}
              isLoading={updateOrgMutation.isPending}
            >
              {t("actions.save")}
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}

/**
 * Everyone in the organization: who is in it, who is asking to be, and how to
 * invite someone.
 *
 * These were three more strips of the organization card, separated from the
 * name and the currency by nothing but a rule — so "Invite a user" read as
 * part of the organization's profile rather than as a subject of its own.
 */
function PeopleCard() {
  const { t } = useTranslation("common");
  const isAdmin = useHasPermission("admin:access");
  // A request for access belongs to no organization: approving it opens an
  // account on the instance, so the instance's superuser decides it — and is
  // the one the bell rings for. Mounted for every administrator, the section
  // asked the API for a list it answered with 403.
  const isSuperuser = useAuthStore((s) => s.user?.is_superuser === true);

  return (
    <Card
      id="people"
      className="p-0 overflow-hidden sm:rounded-xl rounded-none scroll-mt-28"
    >
      <div className="flex items-center gap-3 px-4 py-3.5 border-b border-border">
        <div className="w-9 h-9 rounded-xl flex items-center justify-center bg-primary-50 text-primary-700 dark:bg-primary-500/10 dark:text-primary-500 shrink-0">
          <UsersRound size={17} />
        </div>
        <h2 className="text-sm font-semibold text-on leading-tight">
          {t("settings.organization.peopleTitle")}
        </h2>
      </div>

      <div className="divide-y divide-border">
        <OrganizationMembers />

        {/* Registration requests — the superuser's; renders nothing when
            the queue is empty. */}
        {isSuperuser && <RegistrationRequestsSection />}

        {/* Invite — its own component: picking a role, issuing a link and
            listing what has been issued is a second responsibility next to
 the organization's name and currency. */}
        {isAdmin && <InvitationsSection />}
      </div>
    </Card>
  );
}
