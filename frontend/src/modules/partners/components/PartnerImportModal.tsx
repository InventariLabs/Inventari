import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Select } from "@/components/ui/Select";
import { ImportWizardSheet } from "@/components/import/ImportWizardSheet";
import type { MappingField } from "@/components/import/types";
import { partnersApi } from "@/modules/partners/api/partners";
import { useImportPartners } from "@/modules/partners/hooks/usePartners";
import type { PartnerType } from "@/types";
import type { PartnerImportOutcome } from "@/components/import/types";
import { PARTNER_TYPES } from "@/modules/partners/partnerRoles";
import {
  PARTNER_IMPORT_FIELDS,
  suggestPartnerMapping,
} from "./partnerImportMapping";

interface Props {
  onClose: () => void;
}

/** Label key per column the importer reads; the form's own field names. */
const LABEL_KEYS: Record<(typeof PARTNER_IMPORT_FIELDS)[number], string> = {
  name: "fields.name",
  code: "fields.code",
  type: "fields.type",
  tax_id: "fields.taxId",
  email: "fields.email",
  phone: "fields.phone",
  website: "fields.website",
  contact_person: "fields.contactPerson",
  street: "address.street",
  city: "address.city",
  postal_code: "address.postalCode",
  country: "address.country",
  notes: "fields.notes",
};

export default function PartnerImportModal({ onClose }: Props) {
  const { t } = useTranslation("partners");
  const importMutation = useImportPartners();
  const [defaultType, setDefaultType] = useState<PartnerType>("SUPPLIER");

  const fields: MappingField[] = PARTNER_IMPORT_FIELDS.map((key) => ({
    key,
    label: t(LABEL_KEYS[key]),
    required: key === "name",
  }));

  return (
    <ImportWizardSheet<PartnerImportOutcome>
      onClose={onClose}
      title={t("import.title")}
      formats={t("import.formats")}
      fields={fields}
      requiredField="name"
      analyze={(file) => partnersApi.analyzeImport(file)}
      suggest={suggestPartnerMapping}
      run={(file, mapping) =>
        importMutation.mutateAsync({ file, mapping, defaultType })
      }
      texts={{
        analyzeFailed: t("import.analyzeFailed"),
        importFailed: t("import.failed"),
        wait: t("import.pleaseWait"),
        added: (count) => t("import.added", { count }),
        closeAndView: t("import.closeAndView"),
      }}
      mappingExtras={() => (
        <>
          {/* What the import will and will not do to who is already there. */}
          <p className="px-2 text-sm text-on-secondary">
            {t("import.addOnlyNote")}
          </p>
          <div className="px-2 max-w-xs">
            <Select
              label={t("import.defaultType")}
              value={defaultType}
              onChange={(id) => setDefaultType(id as PartnerType)}
              options={PARTNER_TYPES.map((type) => ({
                id: type,
                name: t(`types.${type}`),
              }))}
            />
          </div>
        </>
      )}
    />
  );
}
