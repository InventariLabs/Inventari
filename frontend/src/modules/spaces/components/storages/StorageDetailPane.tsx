import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  ArrowLeft,
  Clock3,
  Edit2,
  MoveRight,
  PackagePlus,
  Plus,
  Check,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { TypedSlot } from "@/components/Slot";
import { extractApiError } from "@/lib/errors";
import { storagesApi } from "@/lib/api/storages";
import { downloadBlob } from "@/utils/helpers";
import {
  isVirtualUsage,
  virtualUsageLabel,
} from "@/modules/shared/lib/storageUsage";
import { useUpdateStorage } from "@/modules/shared/hooks/useStorageMutations";
import { StorageLabelActions } from "./StorageLabelActions";
import { StoragePath } from "./StoragePath";
import { StorageContentsTab } from "./StorageContentsTab";
import { StorageProductsTab } from "./StorageProductsTab";
import { StorageSettingsTab } from "./StorageSettingsTab";
import type {
  StorageLocation,
  StorageLocationBreadcrumb,
  StorageLocationSummary,
} from "@/types";

type TabValue = "contents" | "products" | "settings" | "moves";

interface StorageDetailPaneProps {
  /** The row the lists show for this location, with its counts. */
  node: StorageLocationSummary;
  storage: StorageLocation;
  /** Root first, this location last. */
  path: StorageLocationBreadcrumb[];
  /** Whether the organization keeps module-owned places out of the lists. */
  excludeModuleContexts: boolean;
  canWriteStorage: boolean;
  canWriteItems: boolean;
  onSelect: (id: string) => void;
  onMove: (ids: string[]) => void;
  onAddInside: () => void;
  onDeleted: () => void;
  /** Opens on Products when the reader arrived from a product link. */
  initialTab?: TabValue;
}

/**
 * The selected location: its full path, its name and what hangs under it.
 *
 * The same actions sit on every level — add a location inside, add a product
 * here, print the label, move it — because after ADR-018 every level is a
 * location, whether it holds shelves or tins. The old screens had a zone
 * page and a location page whose action bars barely overlapped.
 */
export function StorageDetailPane({
  node,
  storage,
  path,
  excludeModuleContexts,
  canWriteStorage,
  canWriteItems,
  onSelect,
  onMove,
  onAddInside,
  onDeleted,
  initialTab = "contents",
}: StorageDetailPaneProps) {
  const { t } = useTranslation(["locations", "common", "items", "labels"]);
  const [tab, setTab] = useState<TabValue>(initialTab);
  const [isRenaming, setIsRenaming] = useState(false);
  const [draftName, setDraftName] = useState(storage.name);
  const renameInputRef = useRef<HTMLInputElement>(null);
  const renameMutation = useUpdateStorage();

  useEffect(() => {
    setDraftName(storage.name);
    setIsRenaming(false);
  }, [storage.id, storage.name]);

  useEffect(() => {
    setTab(initialTab);
  }, [storage.id, initialTab]);

  // The pencil starts an inline edit; the field it reveals takes the focus,
  // or the reader has to find it with the mouse.
  useEffect(() => {
    if (isRenaming) renameInputRef.current?.focus();
  }, [isRenaming]);

  const parent = path.length > 1 ? path[path.length - 2] : undefined;
  const isVirtual = isVirtualUsage(storage.usage);
  const isArchived = Boolean(
    (storage.settings as { archived?: boolean } | null | undefined)?.archived,
  );
  const typeName = storage.location_type?.name ?? "—";

  const saveName = () => {
    const name = draftName.trim();
    if (!name || name === storage.name) {
      setDraftName(storage.name);
      setIsRenaming(false);
      return;
    }
    renameMutation.mutate(
      { id: storage.id, data: { name } },
      {
        onSuccess: () => {
          toast.success(t("locations:messages.storageUpdated"));
          setIsRenaming(false);
        },
        onError: (error: unknown) => {
          setDraftName(storage.name);
          setIsRenaming(false);
          toast.error(extractApiError(error, t("common:errors.actionFailed")));
        },
      },
    );
  };

  const handleDownloadLabel = async () => {
    try {
      const blob = await storagesApi.printLabel(storage.id);
      downloadBlob(blob, `storage_${storage.short_code || storage.name}.png`);
    } catch (error) {
      toast.error(extractApiError(error, t("labels:errorDownloading")));
    }
  };

  return (
    <div className="min-w-0 space-y-5">
      {/* Phone drill-down: the parent's name on the way back, then the path. */}
      <div className="flex items-center gap-2 md:hidden">
        <Button
          variant="ghost"
          size="sm"
          leftIcon={<ArrowLeft size={16} />}
          onClick={() => (parent ? onSelect(parent.id) : onSelect(""))}
        >
          {parent?.name ?? t("locations:path.all")}
        </Button>
      </div>
      <StoragePath path={path} onSelect={onSelect} onAll={() => onSelect("")} />

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            {isRenaming ? (
              <div className="flex w-full max-w-md items-center gap-2">
                <Input
                  ref={renameInputRef}
                  aria-label={t("locations:detail.renameLabel")}
                  value={draftName}
                  onChange={(event) => setDraftName(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") saveName();
                    if (event.key === "Escape") {
                      setDraftName(storage.name);
                      setIsRenaming(false);
                    }
                  }}
                />
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={t("locations:detail.saveName")}
                  onClick={saveName}
                >
                  <Check size={18} />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={t("locations:detail.cancelRename")}
                  onClick={() => {
                    setDraftName(storage.name);
                    setIsRenaming(false);
                  }}
                >
                  <X size={18} />
                </Button>
              </div>
            ) : (
              <>
                <h2 className="min-w-0 truncate text-xl font-semibold text-on">
                  {storage.name}
                </h2>
                {canWriteStorage && (
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t("locations:detail.rename")}
                    onClick={() => setIsRenaming(true)}
                  >
                    <Edit2 size={16} />
                  </Button>
                )}
                {storage.short_code && (
                  <span className="rounded border bg-surface-raised px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase tracking-tight text-on-secondary">
                    {storage.short_code}
                  </span>
                )}
                <span className="text-sm text-on-muted">{typeName}</span>
                {isArchived && (
                  <Badge variant="secondary">
                    {t("locations:archived.badge")}
                  </Badge>
                )}
                {isVirtual && storage.usage && (
                  <Badge variant="secondary">
                    {virtualUsageLabel(t, storage.usage)}
                  </Badge>
                )}
              </>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {canWriteStorage && !isVirtual && (
            <Button
              variant="secondary"
              onClick={onAddInside}
              leftIcon={<Plus size={16} />}
            >
              {t("locations:detail.addInside")}
            </Button>
          )}
          {canWriteItems && !isArchived && !isVirtual && (
            <Link to={`/inventory/items/add?location_id=${storage.id}`}>
              <Button variant="secondary" leftIcon={<PackagePlus size={16} />}>
                {t("locations:detail.addProductHere")}
              </Button>
            </Link>
          )}
          {storage.short_code && (
            <StorageLabelActions
              storage={storage}
              onDownload={() => void handleDownloadLabel()}
            />
          )}
          {canWriteStorage && !isVirtual && (
            <Button
              variant="secondary"
              onClick={() => onMove([storage.id])}
              leftIcon={<MoveRight size={16} />}
            >
              {t("locations:reorg.moveTo")}
            </Button>
          )}
        </div>
      </div>

      {isVirtual && (
        <div
          className="flex items-start gap-2 rounded-xl bg-surface-inset px-4 py-3 text-on-secondary"
          role="note"
        >
          <Clock3 size={18} className="mt-0.5 shrink-0" aria-hidden="true" />
          <div>
            <p className="text-sm font-medium text-on">
              {virtualUsageLabel(t, storage.usage)}
            </p>
            <p className="text-sm">{t("locations:usage.virtualNotice")}</p>
          </div>
        </div>
      )}

      <Tabs
        defaultValue="contents"
        value={tab}
        onValueChange={(value) => setTab(value as TabValue)}
      >
        <TabsList className="w-full">
          <TabsTrigger value="contents">
            {t("locations:tabs.contents")}
          </TabsTrigger>
          <TabsTrigger value="products">
            {t("locations:tabs.products")}
          </TabsTrigger>
          <TabsTrigger value="settings">
            {t("locations:tabs.settings")}
          </TabsTrigger>
          <TabsTrigger value="moves">{t("locations:tabs.moves")}</TabsTrigger>
        </TabsList>
        <TabsContent value="contents" className="pt-4">
          <StorageContentsTab
            parent={node}
            excludeModuleContexts={excludeModuleContexts}
            canWrite={canWriteStorage && !isVirtual}
            onSelect={onSelect}
            onMove={(ids) => onMove(ids)}
            onShowProducts={() => setTab("products")}
          />
        </TabsContent>
        <TabsContent value="products" className="pt-4">
          <StorageProductsTab
            storage={storage}
            summary={node}
            isArchived={isArchived}
            canWriteItems={canWriteItems}
            excludeModuleContexts={excludeModuleContexts}
          />
        </TabsContent>
        <TabsContent value="settings" className="pt-4">
          <StorageSettingsTab
            storage={storage}
            summary={node}
            canWrite={canWriteStorage}
            onDeleted={onDeleted}
          />
        </TabsContent>
        <TabsContent value="moves" className="pt-4">
          <TypedSlot
            name="storage_moves"
            data={{
              storageId: storage.id,
              storageTypeCode: storage.location_type?.type_code,
            }}
            fallback={
              <p className="py-6 text-center text-sm text-on-muted">
                {t("locations:moves.empty")}
              </p>
            }
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
