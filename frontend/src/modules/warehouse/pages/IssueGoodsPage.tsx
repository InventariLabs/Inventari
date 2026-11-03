import {
  PartnerInlineCreate,
  usePartnerCreateLayer,
} from "@/modules/partners/moduleApi";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Card } from "@/components/ui/Card";
import { ChoiceGroup } from "@/components/ui/ChoiceGroup";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { SearchableCombobox } from "@/components/ui/SearchableCombobox";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useReturnTarget } from "@/hooks/useReturnTarget";
import { ReasonCodeField } from "@/modules/shared/components/ReasonCodeField";
import { SCRAP_REASON_CODES } from "@/modules/warehouse/reasonCodes";
import { ActionFooter } from "@/modules/warehouse/components/actions/ActionFooter";
import { WorkspaceFormExtra } from "@/modules/warehouse/components/WorkspaceFormSlots";
import { LocationField } from "@/modules/warehouse/components/LocationField";
import { ActionLines } from "@/modules/warehouse/components/actions/ActionLines";
import { PostedActionResult } from "@/modules/warehouse/components/actions/PostedActionResult";
import {
  useActionDraft,
  type ActionDraft,
} from "@/modules/warehouse/hooks/useActionDraft";
import type {
  DocumentType,
  WarehouseDocument,
} from "@/modules/warehouse/types";

/** What the goods are for, in the words a person answers with. */
type Purpose = "customer" | "internal" | "writeOff";

/** The document each answer writes. The person never picks a type. */
const PURPOSE_TYPE: Record<Purpose, DocumentType> = {
  customer: "OUT",
  internal: "INTERNAL_OUT",
  writeOff: "SCRAP",
};

/** The three answers, each saying what it means. */
function purposeOptions(t: (key: string) => string) {
  return [
    {
      id: "customer",
      label: t("issue.purpose.customer.label"),
      description: t("issue.purpose.customer.description"),
    },
    {
      id: "internal",
      label: t("issue.purpose.internal.label"),
      description: t("issue.purpose.internal.description"),
    },
    {
      id: "writeOff",
      label: t("issue.purpose.writeOff.label"),
      description: t("issue.purpose.writeOff.description"),
    },
  ];
}

/** The button says what the press does for this purpose. */
function postLabel(t: (key: string) => string, purpose: Purpose): string {
  switch (purpose) {
    case "internal":
      return t("issue.post.internal");
    case "writeOff":
      return t("issue.post.writeOff");
    default:
      return t("issue.post.customer");
  }
}

function purposeOf(docType: DocumentType): Purpose {
  if (docType === "INTERNAL_OUT") return "internal";
  if (docType === "SCRAP") return "writeOff";
  return "customer";
}

/** Who gets the goods — asked only when they go to a customer. */
function CustomerField({ draft }: { draft: ActionDraft }) {
  const { t } = useTranslation("warehouse");
  const { workspace, picker, errors } = draft;
  const createPartner = usePartnerCreateLayer({
    roleTypes: picker.partnerTypes,
    onAccepted: workspace.setPartnerId,
  });
  return (
    <>
      <SearchableCombobox
        id="issue-customer"
        label={t("issue.customer")}
        required={workspace.requiresPartner}
        // The field is the customer's on this screen; the shared check's
        // "Partner is required for this document type" named neither.
        error={errors.partner_id ? t("receive.errors.noCustomer") : undefined}
        options={picker.fieldProps.partners}
        onSearchChange={picker.fieldProps.onPartnerSearch}
        loading={picker.fieldProps.partnersLoading}
        value={workspace.partnerId}
        onChange={workspace.setPartnerId}
        placeholder={t("receive.customerPlaceholder")}
        searchPlaceholder={t("form.searchPartner")}
        emptyMessage={t("form.noCustomersFound")}
        createLabel={t("form.createNewPartner")}
        onCreateNew={createPartner.handleCreate}
        title={t("issue.customer")}
      />
      {createPartner.open && (
        <div className="col-span-full">
          <PartnerInlineCreate
            initialName={createPartner.query}
            roleTypes={picker.partnerTypes}
            onCreated={createPartner.handleCreated}
            onCancel={createPartner.handleCancel}
          />
        </div>
      )}
    </>
  );
}

function IssueForm({
  phone,
  onPosted,
}: {
  phone: boolean;
  onPosted: (document: WarehouseDocument, lineCount: number) => void;
}) {
  const { t } = useTranslation("warehouse");
  const draft = useActionDraft("OUT");
  const { workspace, errors } = draft;
  const purpose = purposeOf(workspace.docType);

  return (
    <>
      <Card className="space-y-4 p-4 md:p-6">
        <ChoiceGroup
          label={t("issue.purpose.label")}
          options={purposeOptions(t)}
          value={purpose}
          onChange={(id) => workspace.setDocType(PURPOSE_TYPE[id as Purpose])}
          layout={phone ? "grid2" : "grid"}
          required
        />
        <p className="text-xs text-on-muted">
          {t("issue.documentNote", {
            type: t(`types.${workspace.docType}`),
          })}
        </p>
        <div className="grid grid-cols-1 items-end gap-3 sm:grid-cols-2">
          {purpose === "customer" && draft.partnersEnabled && (
            <CustomerField draft={draft} />
          )}
          <LocationField
            id="issue-source"
            label={t("fields.sourceLocation")}
            required={workspace.requiresSource}
            error={
              errors.source_location_id
                ? t("receive.errors.noSource")
                : undefined
            }
            value={workspace.sourceLocationId}
            onChange={workspace.setSourceLocationId}
            placeholder={t("form.selectSource")}
            searchPlaceholder={t("form.searchLocation")}
            emptyMessage={t("form.noLocationsFound")}
            title={t("fields.sourceLocation")}
          />
        </div>
        {/* A write-off says why: the code is what a report groups by, and
            the note belongs to the document like any other. */}
        {purpose === "writeOff" && (
          <ReasonCodeField
            testId="scrap-reason"
            label={t("reasons.scrap.label")}
            codes={SCRAP_REASON_CODES}
            labelFor={(c) => t(`reasons.scrap.codes.${c}`)}
            code={workspace.scrapReason.code}
            onCodeChange={workspace.scrapReason.setCode}
            note={workspace.notes}
            onNoteChange={workspace.setNotes}
            showErrors={errors.reason_code !== undefined}
          />
        )}
      </Card>

      <WorkspaceFormExtra
        action="issue"
        workspace={workspace}
        registerBeforeSubmit={draft.extensions.registerBeforeSubmit}
        partnerId={purpose === "customer" ? workspace.partnerId || null : null}
        lines={draft.entered}
      />

      <section aria-labelledby="issue-lines" className="space-y-3">
        <div>
          <h2 id="issue-lines" className="text-base font-semibold text-on">
            {t("issue.linesTitle")}
          </h2>
          <p className="text-sm text-on-secondary">{t("issue.linesHint")}</p>
        </div>
        <ActionLines
          draft={draft}
          phone={phone}
          extendedAs="issue"
          onLocationScanned={(id, name) => {
            workspace.setSourceLocationId(id);
            toast.success(
              t("action.sourceScanned", {
                location: name,
              }),
            );
          }}
        />
      </section>

      <ActionFooter
        count={draft.entered.length}
        error={draft.postError}
        pending={draft.isPosting}
        label={postLabel(t, purpose)}
        onPost={() =>
          draft.submit((document) => onPosted(document, draft.entered.length))
        }
      />
    </>
  );
}

/**
 * Issue goods on one screen: what they are for, in words — a customer,
 * production or own use, or damaged and expired — and the system picks the
 * document (a delivery, an internal issue or a write-off). Lines by scan or
 * by search, quantities typed or stepped; a dispatch from a warehouse takes
 * each line from the shelves in the product's removal order. One press posts
 * it, and the answer offers Undo. A phone enters the goods one by one.
 */
export default function IssueGoodsPage() {
  const { t } = useTranslation("warehouse");
  const { setHeader } = useModulePageHeader();
  const backTo = useReturnTarget() ?? "/warehouse/todo";
  const canWrite = useCanWrite("warehouse");
  const phone = useMediaQuery("(max-width: 767px)");
  const [posted, setPosted] = useState<{
    document: WarehouseDocument;
    lineCount: number;
  } | null>(null);
  // A fresh draft for every issue: the form remounts on this key.
  const [round, setRound] = useState(0);

  useEffect(() => {
    setHeader({
      title: t("issue.title"),
      subtitle: t("issue.subtitle"),
      backTo,
    });
  }, [setHeader, t, backTo]);

  return (
    <div className="space-y-6">
      <ReadOnlyNotice module="warehouse" />
      {posted ? (
        <PostedActionResult
          document={posted.document}
          action="issue"
          lineCount={posted.lineCount}
          onAnother={() => {
            setPosted(null);
            setRound((value) => value + 1);
          }}
        />
      ) : (
        canWrite && (
          <IssueForm
            key={round}
            phone={phone}
            onPosted={(document, lineCount) =>
              setPosted({ document, lineCount })
            }
          />
        )
      )}
    </div>
  );
}
