import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { InlineQueryError } from "@/components/ui/QueryResult";
import {
  useDocumentProfile,
  useUpdateDocumentProfile,
} from "@/modules/warehouse/hooks/useDocumentProfile";
import { useDocumentTemplates } from "@/modules/shared/hooks/useDocumentTemplates";
import type { DocumentTemplate } from "@/modules/shared/lib/templates";
import { usePageSavePart } from "@/module-sdk";
import { useOrganization } from "@/modules/settings/hooks/useOrganization";

/** Whether the issuer block of a printout would come out empty. */
function issuerIsEmpty(
  org: { tax_id?: string | null; address?: unknown } | undefined,
): boolean {
  if (!org) return false;
  const address = (org.address ?? {}) as { street?: string; city?: string };
  return !org.tax_id && !address.street && !address.city;
}

/**
 * Which layout a document printout uses: the automatic default, one of the
 * two built-in families or one of the organization's own templates.
 *
 * Automatic is what a new organization starts on: the Polish PZ form for an
 * organization whose country is Poland, the standard layout everywhere else.
 * Either way the words and dates are written in the language the printout is
 * asked in, so nobody has to find this screen to get a printout they can hand
 * to an accountant.
 *
 * The templates screen promises "copy a built-in to change the printout";
 * this selector is what makes the copy actually print — the profile stores
 * the choice as ``default_template_id``, and the PDF endpoint renders that
 * template's HTML instead of the filesystem family.
 */
export function PrintLayoutSelector() {
  const { t } = useTranslation("warehouse");
  const { data: profile } = useDocumentProfile();
  const {
    data: templates = [],
    isError: templatesFailed,
    error: templatesError,
    refetch: refetchTemplates,
  } = useDocumentTemplates("warehouse");
  const updateMutation = useUpdateDocumentProfile();
  const { data: organization } = useOrganization();

  const stored =
    profile?.default_template_id ?? profile?.print_template ?? "auto";
  // The pick waits for the page's Save; `null` is "not touched".
  const [choice, setChoice] = useState<string | null>(null);
  const selected = choice ?? stored;

  const save = async () => {
    if (choice === null) return;
    await updateMutation.mutateAsync(
      choice === "auto" || choice === "standard" || choice === "pl_pz"
        ? { print_template: choice, default_template_id: null }
        : { default_template_id: choice },
    );
    setChoice(null);
  };
  usePageSavePart("printLayout", choice !== null && choice !== stored, save);

  return (
    <section className="space-y-6">
      <div>
        <h2 className="text-sm font-semibold text-on">
          {t("profile.printLayout")}
        </h2>
        <p className="text-xs text-on-muted mt-1">
          {t("profile.printLayoutHint")}
        </p>
      </div>
      <div className="space-y-1.5 max-w-md">
        <NativeSelect
          aria-label={t("profile.printLayout")}
          value={selected}
          onChange={(e) => setChoice(e.target.value)}
        >
          <option value="auto">{t("profile.layoutAuto")}</option>
          <option value="standard">
            {t("profile.layoutStandard", "Standard layout")}
          </option>
          <option value="pl_pz">
            {t("profile.layoutPlPz", "PL PZ layout")}
          </option>
          {templates.map((tpl: DocumentTemplate) => (
            <option key={tpl.id} value={tpl.id}>
              {tpl.name}
            </option>
          ))}
        </NativeSelect>
        {/* Without the organization's templates the list ends at the two
            built-in layouts, and a saved custom choice has no option to show. */}
        {templatesFailed && (
          <InlineQueryError
            error={templatesError}
            onRetry={() => void refetchTemplates()}
          />
        )}
        {/* What the change reaches: this is the org-wide fallback, and a
            template written for a document's type (Templates screen) still
            wins for that type. Saving here used to re-dress every printout
            in the organization with nothing on screen saying so. */}
        <p className="text-xs text-on-muted">{t("profile.printLayoutScope")}</p>
        {selected === "auto" && (
          <p className="text-xs text-on-muted">{t("profile.layoutAutoRule")}</p>
        )}
        {/* The issuer block is read from the organization, not from this
            profile; left empty it prints a letterhead with no address and
            no tax id, and nothing on the way to "Download PDF" said so. */}
        {issuerIsEmpty(organization) && (
          <p role="status" className="text-xs text-on-warning">
            {t("profile.issuerEmpty")}{" "}
            <Link
              to="/settings"
              className="font-semibold text-on-primary hover:underline"
            >
              {t("profile.issuerEmptyLink")}
            </Link>
          </p>
        )}
      </div>
    </section>
  );
}
