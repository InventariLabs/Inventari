import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { PackageOpen } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { queryKeys } from "@/hooks/queries/keys";
import { useLocationsById } from "@/module-sdk";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useReturnTarget } from "@/hooks/useReturnTarget";
import { storagesApi } from "@/lib/api/storages";
import { extractApiError } from "@/lib/errors";
import { itemSku, productCode, type Item } from "@/types";
import { ActionFooter } from "@/modules/warehouse/components/actions/ActionFooter";
import { LocationField } from "@/modules/warehouse/components/LocationField";
import { ActionLines } from "@/modules/warehouse/components/actions/ActionLines";
import { PostedActionResult } from "@/modules/warehouse/components/actions/PostedActionResult";
import type { ReceiptDraftLine } from "@/modules/warehouse/components/documentFormShared";
import { useActionDraft } from "@/modules/warehouse/hooks/useActionDraft";
import type { WarehouseDocument } from "@/modules/warehouse/types";

/** A line moving the whole of one record off its shelf. */
function wholeRecordLine(item: Item): ReceiptDraftLine {
  return {
    _key: crypto.randomUUID(),
    item_id: item.id,
    name: item.name,
    brand: item.brand ?? undefined,
    barcode: productCode(item) ?? undefined,
    sku: itemSku(item) ?? undefined,
    image_url: item.image_url ?? undefined,
    quantity: Number(item.quantity),
    uom_id: item.uom_id ?? null,
    batch_number: "",
    expiry_date: "",
    notes: "",
    unit_price: "",
    tax_rate: "",
  };
}

function MoveForm({
  phone,
  onPosted,
}: {
  phone: boolean;
  onPosted: (document: WarehouseDocument, lineCount: number) => void;
}) {
  const { t } = useTranslation("warehouse");
  const queryClient = useQueryClient();
  const draft = useActionDraft("INT");
  const { workspace, errors } = draft;
  const [loadingShelf, setLoadingShelf] = useState(false);
  const { byId: sourcePlace } = useLocationsById([workspace.sourceLocationId]);
  const nameOf = (id: string) => sourcePlace.get(id)?.name ?? "";
  // "Everything in" reads the records standing on the source itself. A
  // location with places inside it keeps its stock on them, so offered there
  // the button answered "Nothing more stands in Main warehouse" over full
  // shelves: it is offered for a location nothing else sits in.
  const sourceHoldsPlaces =
    (sourcePlace.get(workspace.sourceLocationId)?.direct_children_count ?? 0) >
    0;

  // Everything standing on the source itself, each record whole. Records
  // already on the list keep the quantity somebody set for them.
  const takeEverything = async () => {
    const source = workspace.sourceLocationId;
    setLoadingShelf(true);
    try {
      const items = await queryClient.fetchQuery({
        queryKey: queryKeys.storages.items(source),
        queryFn: () => storagesApi.getItems(source),
      });
      const listed = new Set(draft.entered.map((line) => line.item_id));
      const added = items.filter(
        (item) => Number(item.quantity) > 0 && !listed.has(item.id),
      );
      added.forEach((item) => workspace.appendLine(wholeRecordLine(item)));
      toast.success(
        added.length > 0
          ? t("move.everythingAdded", { count: added.length })
          : t("move.everythingNone", { location: nameOf(source) }),
      );
    } catch (error) {
      toast.error(extractApiError(error, t("move.everythingFailed")));
    } finally {
      setLoadingShelf(false);
    }
  };

  return (
    <>
      <Card className="space-y-4 p-4 md:p-6">
        <div className="grid grid-cols-1 items-end gap-3 sm:grid-cols-2">
          <LocationField
            id="move-source"
            label={t("fields.sourceLocation")}
            required
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
          <LocationField
            id="move-target"
            except={[workspace.sourceLocationId]}
            label={t("fields.targetLocation")}
            required
            error={
              errors.target_location_id
                ? t("receive.errors.noWarehouse")
                : undefined
            }
            value={workspace.targetLocationId}
            onChange={workspace.setTargetLocationId}
            placeholder={t("form.selectTarget")}
            searchPlaceholder={t("form.searchLocation")}
            emptyMessage={t("form.noLocationsFound")}
            title={t("fields.targetLocation")}
          />
        </div>
        <p className="text-xs text-on-muted">{t("move.scanHint")}</p>
        {workspace.sourceLocationId && !sourceHoldsPlaces && (
          <Button
            variant="outline"
            leftIcon={<PackageOpen size={16} />}
            disabled={loadingShelf}
            onClick={() => void takeEverything()}
          >
            {t("move.everything", {
              location: nameOf(workspace.sourceLocationId),
            })}
          </Button>
        )}
      </Card>

      <section aria-labelledby="move-lines" className="space-y-3">
        <h2 id="move-lines" className="text-base font-semibold text-on">
          {t("move.linesTitle")}
        </h2>
        <ActionLines
          draft={draft}
          phone={phone}
          wholeRecord
          onLocationScanned={(id, name) => {
            // The shelf the goods come from is scanned first, the one they
            // go to once they are on the list.
            if (draft.entered.length === 0) {
              workspace.setSourceLocationId(id);
              toast.success(t("action.sourceScanned", { location: name }));
            } else {
              workspace.setTargetLocationId(id);
              toast.success(t("action.targetScanned", { location: name }));
            }
          }}
        />
      </section>

      <ActionFooter
        count={draft.entered.length}
        error={draft.postError}
        pending={draft.isPosting}
        label={t("move.post")}
        onPost={() =>
          draft.submit((document) => onPosted(document, draft.entered.length))
        }
      />
    </>
  );
}

/**
 * Move goods on one screen: from where to where — chosen or scanned — and
 * what: lines by scan or search, or everything standing on the shelf. No
 * prices; one press posts the transfer, and the answer offers Undo. A phone
 * enters the goods one by one.
 */
export default function MoveGoodsPage() {
  const { t } = useTranslation("warehouse");
  const { setHeader } = useModulePageHeader();
  const backTo = useReturnTarget() ?? "/warehouse/todo";
  const canWrite = useCanWrite("warehouse");
  const phone = useMediaQuery("(max-width: 767px)");
  const [posted, setPosted] = useState<{
    document: WarehouseDocument;
    lineCount: number;
  } | null>(null);
  // A fresh draft for every move: the form remounts on this key.
  const [round, setRound] = useState(0);

  useEffect(() => {
    setHeader({ title: t("move.title"), subtitle: t("move.subtitle"), backTo });
  }, [setHeader, t, backTo]);

  return (
    <div className="space-y-6">
      <ReadOnlyNotice module="warehouse" />
      {posted ? (
        <PostedActionResult
          document={posted.document}
          action="move"
          lineCount={posted.lineCount}
          onAnother={() => {
            setPosted(null);
            setRound((value) => value + 1);
          }}
        />
      ) : (
        canWrite && (
          <MoveForm
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
