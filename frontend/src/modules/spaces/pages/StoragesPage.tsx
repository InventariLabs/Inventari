import { useCallback, useEffect, useRef, useState } from "react";
import { Archive, Boxes, Info, Plus, SearchX } from "lucide-react";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { useTranslation } from "react-i18next";
import LoadingSpinner from "@/components/LoadingSpinner";
import { Button } from "@/components/ui/Button";
import { EmptyState, EmptyStateAction } from "@/components/ui/EmptyState";
import { QueryError } from "@/components/ui/QueryResult";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { HiddenRecordsNotice } from "@/modules/shared/components/HiddenRecordsNotice";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useShowModuleData } from "@/modules/settings/hooks/useOrganization";
import {
  useStorage,
  useStoragesTree,
} from "@/modules/shared/hooks/useStorages";
import { useHiddenStorageCount } from "@/modules/spaces/hooks/useHiddenStorageCount";
import { useStorageMove } from "@/modules/spaces/hooks/useStorageMove";
import { useSelectedStorage } from "@/modules/spaces/hooks/useSelectedStorage";
import { isVirtualUsage } from "@/modules/shared/lib/storageUsage";
import { isNotFoundError } from "@/lib/errors";
import { StoragesEmptyState } from "@/modules/spaces/components/StoragesEmptyState";
import type { StorageLocationNode, StorageLocationSummary } from "@/types";
import StorageWizard from "@/modules/spaces/components/StorageWizard";
import { StorageTreePanel } from "@/modules/spaces/components/storages/StorageTreePanel";
import { StorageDetailPane } from "@/modules/spaces/components/storages/StorageDetailPane";
import { StorageMovePicker } from "@/modules/spaces/components/storages/StorageMovePicker";
import { LocationMoveQuestion } from "@/modules/spaces/components/LocationMoveQuestion";

/**
 * Storages as one screen: the location tree on the left, the selected
 * location on the right.
 *
 * The old screen was three screens stacked — a list of zone cards, a zone of
 * location cards, and a location's own page — each with its own Edit dialog
 * and no place showing the whole path. Restructuring was a fourth screen
 * behind Reorganize, saved separately from the changes it made.
 *
 * `/inventory/locations` is "nothing selected"; `/inventory/locations/:id` and
 * the old `/inventory/locations/zone/:zoneId` open this screen with that
 * node selected, so every link written before still lands somewhere true.
 */
export default function StoragesPage() {
  const { t } = useTranslation(["locations", "common"]);
  const { id, zoneId } = useParams<{ id?: string; zoneId?: string }>();
  const selectedId = id ?? zoneId;
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("locations");
  const canWriteItems = useCanWrite("items");

  const excludeModuleContexts = !useShowModuleData();
  // The top level only; deeper levels load when the reader opens them.
  const {
    data: roots = [],
    isLoading: isTreeLoading,
    isError: isTreeError,
    refetch: refetchTree,
  } = useStoragesTree(undefined, { excludeModuleContexts, depth: 1 });

  const selected = useSelectedStorage(selectedId, excludeModuleContexts);
  const node = selected.summary;
  const {
    data: storage,
    isLoading: isDetailLoading,
    isError: isDetailError,
    error: detailError,
    refetch: refetchDetail,
  } = useStorage(selectedId ?? "");

  const [wizardParentId, setWizardParentId] = useState<string | undefined>();
  const [isWizardOpen, setIsWizardOpen] = useState(false);
  const [moveIds, setMoveIds] = useState<string[] | null>(null);
  const [moveFocusConsumed, setMoveFocusConsumed] = useState(false);
  const { move, moveQuestion } = useStorageMove();

  const hiddenStorageCount = useHiddenStorageCount(
    excludeModuleContexts,
    isTreeLoading,
    false,
  );

  // The location the person chose last. The detail pane switches a render
  // after the press that chose it, so a press on "Add location inside" right
  // behind the choice still lands on the pane of the previous location; the
  // wizard has to open on the one that was chosen.
  const chosenId = useRef(selectedId);
  useEffect(() => {
    chosenId.current = selectedId;
  }, [selectedId]);

  const select = useCallback(
    (nextId: string) => {
      chosenId.current = nextId || undefined;
      navigate(
        nextId ? `/inventory/locations/${nextId}` : "/inventory/locations",
      );
    },
    [navigate],
  );

  useEffect(() => {
    setHeader({
      title: t("locations:title"),
      subtitle: t("locations:masterDetailSubtitle"),
      actions: canWrite ? (
        <Button
          onClick={() => {
            setWizardParentId(undefined);
            setIsWizardOpen(true);
          }}
          leftIcon={<Plus size={16} />}
        >
          {t("locations:actions.openWizard")}
        </Button>
      ) : undefined,
    });
  }, [canWrite, setHeader, t]);

  // The scan sheet's Move names the field it wants in the address; on this
  // screen that field is the move picker, opened once when the page arrives.
  useEffect(() => {
    if (moveFocusConsumed || !node) return;
    if (searchParams.get("focus") !== "move") return;
    setMoveIds([node.id]);
    setMoveFocusConsumed(true);
  }, [moveFocusConsumed, node, searchParams]);

  const refetchAll = () => {
    refetchTree();
    selected.refetch();
  };

  if (isTreeLoading) return <LoadingSpinner />;
  if (isTreeError) return <QueryError onRetry={refetchAll} />;

  const hiddenNotice =
    hiddenStorageCount > 0 && roots.length > 0 ? (
      <HiddenRecordsNotice
        message={t("locations:hidden.inlineCount", {
          count: hiddenStorageCount,
        })}
        actionLabel={t("locations:hidden.openSettings")}
      />
    ) : null;

  if (roots.length === 0 && !selectedId) {
    return (
      <div className="space-y-6 animate-in fade-in duration-500">
        <ReadOnlyNotice module="locations" />
        <StoragesEmptyState
          hasHidden={hiddenStorageCount > 0}
          onAddFirst={() => {
            setWizardParentId(undefined);
            setIsWizardOpen(true);
          }}
        />
        <StorageWizard
          isOpen={isWizardOpen}
          onClose={() => setIsWizardOpen(false)}
        />
      </div>
    );
  }

  const withheld = withheldFor(selected.withheld);

  const detailPane = (() => {
    if (withheld) {
      return <WithheldPane withheld={withheld} onBack={() => select("")} />;
    }
    if (selectedId && selected.isError) {
      return <QueryError onRetry={refetchAll} />;
    }
    // Only the pane waits for the chosen place: the tree it was chosen from,
    // its open branches and a wizard opened right behind the choice stay.
    if (selected.isLoading) return <LoadingSpinner />;
    if (selectedId && !node) {
      return (
        <EmptyState
          icon={SearchX}
          title={t("locations:storageNotFound")}
          description={t("locations:storageNotFoundDescription")}
          primaryAction={
            <EmptyStateAction
              label={t("locations:detail.backToList")}
              onClick={() => select("")}
            />
          }
        />
      );
    }
    if (!node) {
      return (
        <div className="hidden rounded-xl border border-dashed border-border bg-surface-card p-8 md:block">
          <EmptyState
            icon={Boxes}
            title={t("locations:select.title")}
            description={t("locations:select.description")}
          />
        </div>
      );
    }
    if (isDetailError && !isNotFoundError(detailError)) {
      return <QueryError onRetry={refetchDetail} />;
    }
    if (isDetailLoading || !storage) return <LoadingSpinner />;
    return (
      <StorageDetailPane
        node={node}
        storage={storage}
        path={selected.path}
        excludeModuleContexts={excludeModuleContexts}
        canWriteStorage={canWrite}
        canWriteItems={canWriteItems}
        onSelect={select}
        onMove={setMoveIds}
        onAddInside={() => {
          setWizardParentId(chosenId.current ?? node.id);
          setIsWizardOpen(true);
        }}
        onDeleted={() => {
          const parentId = node.parent_id;
          select(parentId ?? "");
        }}
        initialTab={
          searchParams.get("configure") === "true" ? "settings" : "contents"
        }
      />
    );
  })();

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <ReadOnlyNotice module="locations" />
      {hiddenNotice}

      <div className="grid grid-cols-1 gap-6 md:grid-cols-[minmax(280px,360px)_minmax(0,1fr)]">
        <aside className="hidden md:block">
          <div className="sticky top-4 rounded-xl border border-border bg-surface-card p-3">
            <StorageTreePanel
              excludeModuleContexts={excludeModuleContexts}
              selectedId={selectedId}
              openPath={selected.path.slice(0, -1).map((step) => step.id)}
              onSelect={select}
              canWrite={canWrite}
              onMoveTo={(nodeId) => setMoveIds([nodeId])}
              onDragMove={(nodeId, parentId) =>
                void move([{ id: nodeId, parent_id: parentId }])
              }
            />
          </div>
        </aside>

        {/* Phone without a selection: the drill-down's first level is the
            roots themselves, not a tree squeezed beside nothing. */}
        {!selectedId && <MobileRoots nodes={roots} onSelect={select} />}

        <section className="min-w-0">{detailPane}</section>
      </div>

      <StorageWizard
        isOpen={isWizardOpen}
        onClose={() => {
          setIsWizardOpen(false);
          setWizardParentId(undefined);
        }}
        preselectedParentId={wizardParentId}
      />

      <LocationMoveQuestion {...moveQuestion} />

      {moveIds && (
        <StorageMovePicker
          open
          movingIds={moveIds}
          excludeModuleContexts={excludeModuleContexts}
          onClose={() => setMoveIds(null)}
          onPick={(parentId) => {
            const ids = moveIds;
            setMoveIds(null);
            void move(
              ids.map((moveId) => ({ id: moveId, parent_id: parentId })),
            );
          }}
        />
      )}
    </div>
  );
}

/**
 * Why a location the tree does not hold is not on it — module-owned, virtual
 * or archived — instead of calling it missing.
 */
type WithheldLocation = {
  kind: "module" | "virtual" | "archived";
  name: string;
};

function withheldFor(
  found: StorageLocationSummary | undefined,
): WithheldLocation | null {
  if (!found) return null;
  const archived = Boolean(
    (found.settings as { archived?: boolean } | null | undefined)?.archived,
  );
  if (found.context_tag) return { kind: "module", name: found.name };
  if (isVirtualUsage(found.usage)) return { kind: "virtual", name: found.name };
  if (archived) return { kind: "archived", name: found.name };
  return null;
}

function WithheldPane({
  withheld,
  onBack,
}: {
  withheld: WithheldLocation;
  onBack: () => void;
}) {
  const { t } = useTranslation(["locations", "common"]);
  const copy = {
    module: {
      icon: Boxes,
      title: t("locations:zoneModule.title"),
      description: t("locations:zoneModule.description", {
        name: withheld.name,
      }),
    },
    virtual: {
      icon: Info,
      title: t("locations:zoneVirtual.title"),
      description: t("locations:zoneVirtual.description", {
        name: withheld.name,
      }),
    },
    archived: {
      icon: Archive,
      title: t("locations:zoneArchived.title"),
      description: t("locations:zoneArchived.description", {
        name: withheld.name,
      }),
    },
  }[withheld.kind];
  return (
    <EmptyState
      icon={copy.icon}
      title={copy.title}
      description={copy.description}
      primaryAction={
        <EmptyStateAction
          label={t("locations:detail.backToList")}
          onClick={onBack}
        />
      }
    />
  );
}

/** The phone's first level: the roots themselves. */
function MobileRoots({
  nodes,
  onSelect,
}: {
  nodes: StorageLocationNode[];
  onSelect: (id: string) => void;
}) {
  const { t } = useTranslation("locations");
  return (
    <section className="space-y-3 md:hidden">
      <h2 className="text-lg font-semibold text-on">{t("path.all")}</h2>
      <ul className="divide-y divide-border rounded-xl border border-border">
        {nodes.map((root) => (
          <li key={root.id}>
            <Button
              variant="ghost"
              size="row"
              onClick={() => onSelect(root.id)}
              className="justify-between"
            >
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium text-on">
                  {root.name}
                </span>
                <span className="block text-xs text-on-muted">
                  {t("counts.inSublocations", {
                    count: root.children_count,
                  })}
                </span>
              </span>
              <span className="shrink-0 text-right">
                <span className="block text-sm tabular-nums text-on">
                  {root.subtree_items_count}
                </span>
                <span className="block text-[10px] text-on-muted">
                  {t("card.unit", { count: root.subtree_items_count })}
                </span>
              </span>
            </Button>
          </li>
        ))}
      </ul>
      {/* The tree's aside, where this link lives on a desktop, is not drawn on
          a phone; a location archived from there could only be restored by
          typing the address. */}
      <Link
        to="/inventory/locations/archived"
        className="inline-flex min-h-11 items-center gap-1.5 px-1 text-sm text-on-muted hover:text-on"
      >
        <Archive size={14} aria-hidden="true" />
        {t("tree.archivedLink")}
      </Link>
    </section>
  );
}
