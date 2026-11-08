import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router-dom";
import { PackageCheck, Plus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { ScannerReadyHint } from "@/components/ui/ScannerReadyHint";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useScannerInput } from "@/hooks/useScannerInput";
import {
  packingApi,
  type PackingLineOut,
  type PackingView,
} from "@/modules/warehouse/api/packing";
import { useDocumentScanSession } from "@/modules/warehouse/hooks/useDocumentScanSession";
import {
  usePacking,
  usePackingWrite,
} from "@/modules/warehouse/hooks/usePacking";
import type { ShipmentCreate } from "@/modules/warehouse/api/shipments";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import { PackageCard } from "./PackageCard";
import { PACKING_HASH } from "./packingHash";
import { PackingFooter } from "./PackingFooter";
import { PackLineSheet } from "./PackLineSheet";
import { ToPackList } from "./ToPackList";

/** Goods leaving the warehouse — the types the server packs (`is_dispatch`). */
const DISPATCH_TYPES: ReadonlySet<string> = new Set([
  "OUT",
  "INTERNAL_OUT",
  "WZ",
  "RW",
]);

export const isPackedType = (type: string) => DISPATCH_TYPES.has(type);

/** A dispatch whose packing can be offered once nothing is being picked. */
function packingApplies(document: WarehouseDocument): boolean {
  return (
    isPackedType(document.type) &&
    document.status === "CONFIRMED" &&
    document.lines.some((line) => Number(line.done_quantity) > 0)
  );
}

/** A dispatch that has left: its packages, if it had any, are a record. */
const isShippedDispatch = (document: WarehouseDocument) =>
  isPackedType(document.type) && document.status === "COMPLETED";

/** The package whose quantity of a line grew between two views, by name. */
function grownLine(
  before: PackingView | undefined,
  after: PackingView,
  packageId: string,
): string | null {
  const held = new Map(
    before?.packages
      .find((p) => p.id === packageId)
      ?.lines.map((ln) => [ln.document_line_id, Number(ln.quantity)]),
  );
  const grown = after.packages
    .find((p) => p.id === packageId)
    ?.lines.find(
      (ln) => Number(ln.quantity) > (held.get(ln.document_line_id) ?? 0),
    );
  return grown?.product_name ?? null;
}

interface Props {
  document: WarehouseDocument;
  onComplete: (shipment?: ShipmentCreate) => void;
  isCompletePending: boolean;
}

/**
 * The Pack step of a picked dispatch: packages filled by scan or by tap, the
 * slip and the label for each, and the completion that ships them.
 *
 * Worked on between picking and completion: while a picking session is open
 * the goods are still coming off the shelf. Once the dispatch is completed
 * the packages stay, read-only, with their slips and labels — the slip of a
 * shipped dispatch is what a returned box is checked against, and the server
 * prints it after completion too.
 */
export function DocumentPackingStep(props: Props) {
  const working = usePackingStepShown(props.document);
  if (!working && !isShippedDispatch(props.document)) return null;
  return <PackingStepBody {...props} />;
}

/**
 * Whether the Pack step stands on the document's page right now: a picked
 * dispatch with no picking session still open over it. Anything that leads
 * the reader to the step asks this, so it never leads to a step that is not
 * there.
 */
export function usePackingStepShown(
  document: WarehouseDocument | undefined,
): boolean {
  const applies = document ? packingApplies(document) : false;
  const { data: session, isPending } = useDocumentScanSession(
    document?.id ?? "",
    { enabled: applies },
  );
  // A finished session is the picking done: packing is what comes after it.
  const picking = session != null && session.status !== "finished";
  return applies && !isPending && !picking;
}

function PackingStepBody({ document, onComplete, isCompletePending }: Props) {
  const { t } = useTranslation("warehouse");
  const canWrite = useCanWrite("warehouse");
  const reveal = useLocation().hash === PACKING_HASH;
  const cardRef = useRef<HTMLDivElement>(null);
  const { data: view, error, refetch } = usePacking(document.id);
  const write = usePackingWrite(document.id);
  const [chosenId, setChosenId] = useState<string | null>(null);
  const [tapped, setTapped] = useState<PackingLineOut | null>(null);

  const packages = view?.packages ?? [];
  const remaining = (view?.lines ?? []).filter(
    (line) => Number(line.remaining_quantity) > 0,
  );
  const editable = Boolean(view?.editable) && canWrite;
  // The chosen package while it stands, else the newest: a package just
  // opened is the one the next scan is for.
  const selected =
    packages.find((p) => p.id === chosenId) ?? packages.at(-1) ?? null;

  /** Into the selected package — or a new one, when there is none yet. */
  const intoPackage = (
    fill: (packageId: string) => Promise<PackingView>,
  ): Promise<PackingView> => {
    if (selected) return fill(selected.id);
    return packingApi.create(document.id).then((opened) => {
      const pkg = opened.packages.at(-1);
      setChosenId(pkg?.id ?? null);
      return pkg ? fill(pkg.id) : opened;
    });
  };

  useScannerInput(
    (code) => {
      write.mutate(
        () =>
          intoPackage((packageId) =>
            packingApi.scan(document.id, packageId, code),
          ),
        {
          onSuccess: (after) => {
            const pkg = selected ?? after.packages.at(-1);
            if (!pkg) return;
            const product = grownLine(view, after, pkg.id);
            toast.success(
              t("packing.scanned", {
                product: product ?? code,
                code: pkg.code,
              }),
            );
          },
        },
      );
    },
    { enabled: editable && remaining.length > 0 && !tapped },
  );

  const loaded = view !== undefined;
  useEffect(() => {
    if (!reveal || !loaded) return;
    cardRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }, [reveal, loaded]);

  if (error) {
    return <InlineQueryError error={error} onRetry={() => void refetch()} />;
  }
  if (!view) return null;
  // Shipped without packages: there is no record to show.
  if (!view.editable && packages.length === 0) return null;

  const packTapped = (quantity: number) => {
    if (!tapped) return;
    const line = tapped;
    write.mutate(
      () =>
        intoPackage((packageId) => {
          const held = Number(
            packages
              .find((p) => p.id === packageId)
              ?.lines.find(
                (ln) => ln.document_line_id === line.document_line_id,
              )?.quantity ?? 0,
          );
          return packingApi.setLine(
            document.id,
            packageId,
            line.document_line_id,
            String(held + quantity),
          );
        }),
      { onSuccess: () => setTapped(null) },
    );
  };

  return (
    <Card ref={cardRef} className="p-4 sm:p-5 space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-on">{t("packing.title")}</h2>
        <p className="text-sm text-on-secondary mt-1">
          {view.editable ? t("packing.subtitle") : t("packing.subtitleShipped")}
        </p>
      </div>

      {editable && remaining.length > 0 && (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            <Button
              leftIcon={<PackageCheck size={16} />}
              isLoading={write.isPending}
              onClick={() =>
                write.mutate(() => packingApi.packAll(document.id), {
                  onSuccess: (after) =>
                    setChosenId(after.packages.at(-1)?.id ?? null),
                })
              }
            >
              {packages.length === 0
                ? t("packing.packAll")
                : t("packing.packRest")}
            </Button>
            <Button
              variant="outline"
              leftIcon={<Plus size={16} />}
              disabled={write.isPending}
              onClick={() =>
                write.mutate(() => packingApi.create(document.id), {
                  onSuccess: (after) =>
                    setChosenId(after.packages.at(-1)?.id ?? null),
                })
              }
            >
              {t("packing.addPackage")}
            </Button>
          </div>
          <ScannerReadyHint />
        </div>
      )}

      {view.editable && (
        <ToPackList
          lines={remaining}
          packed={packages.length > 0}
          onTap={editable ? setTapped : undefined}
        />
      )}

      {packages.length > 0 && (
        <ul className="space-y-3" aria-label={t("packing.packages")}>
          {packages.map((pkg) => (
            <PackageCard
              key={`${pkg.id}-${pkg.weight_kg ?? ""}`}
              documentId={document.id}
              pkg={pkg}
              selected={pkg.id === selected?.id}
              editable={editable}
              filling={editable && remaining.length > 0}
              selectable={packages.length > 1}
              onSelect={() => setChosenId(pkg.id)}
              onRemoveLine={(lineId) =>
                write.mutate(() =>
                  packingApi.setLine(document.id, pkg.id, lineId, "0"),
                )
              }
              onWeight={(weightKg) =>
                write.mutate(() =>
                  packingApi.setWeight(document.id, pkg.id, weightKg),
                )
              }
              onRemove={() =>
                write.mutate(() => packingApi.remove(document.id, pkg.id))
              }
            />
          ))}
        </ul>
      )}

      <PackingFooter
        document={document}
        packageCount={packages.length}
        canComplete={editable}
        packingLeft={remaining.length > 0}
        isCompletePending={isCompletePending}
        isWritePending={write.isPending}
        onComplete={onComplete}
      />

      {tapped && (
        <PackLineSheet
          line={tapped}
          packageCode={selected?.code ?? null}
          isPending={write.isPending}
          onConfirm={packTapped}
          onCancel={() => setTapped(null)}
        />
      )}
    </Card>
  );
}
