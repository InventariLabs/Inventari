import { Link } from "react-router-dom";
import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { locationPathBelowName } from "@/utils/helpers";
import { useQueryClient } from "@tanstack/react-query";
import { Plus, Pencil, Trash2, MapPin } from "lucide-react";
import { toast } from "sonner";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanWrite } from "@/hooks/useCanWrite";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { LocationCombobox, useDebounce, useLocationPages } from "@/module-sdk";
import { Card, CardContent } from "@/components/ui/Card";
import { useConfirm } from "@/hooks/useConfirm";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState, EmptyStateAction } from "@/components/ui/EmptyState";
import { QueryError } from "@/components/ui/QueryResult";
import LoadingSpinner from "@/components/LoadingSpinner";
import { ListControlBar } from "@/components/ui/ListControlBar";
import { useStorage } from "@/modules/shared/hooks/useStorages";
import {
  useCreateStorageHierarchy,
  useUpdateStorage,
  useDeleteStorage,
} from "@/modules/shared/hooks/useStorageMutations";
import { locationDeleteConsequences } from "@/modules/shared/lib/locationDelete";
import { queryKeys } from "@/hooks/queries/keys";
import type { StorageLocationSummary } from "@/types";

// ---------------------------------------------------------------------------
// Inline form for add / edit
// ---------------------------------------------------------------------------

interface LocationFormProps {
  initial?: { name: string; description: string };
  onSave: (name: string, description: string, parentId: string) => void;
  onCancel: () => void;
  isSaving: boolean;
}

/**
 * The edit form, filled from where the description actually lives.
 *
 * The list endpoint answers with `StorageLocationSummary`, which carries no
 * `description` (see the type) — so this form opened empty for every location
 * that had one, and the row beneath it rendered a description block that could
 * never appear. `GET /locations/{id}` is where the backend sends it.
 */
function EditingLocationForm({
  id,
  name,
  onSave,
  onCancel,
  isSaving,
}: {
  id: string;
  name: string;
  onSave: (name: string, description: string) => void;
  onCancel: () => void;
  isSaving: boolean;
}) {
  const { data } = useStorage(id);
  return (
    <LocationForm
      // Remount once the detail lands, so the form's own state picks it up.
      key={data ? "loaded" : "pending"}
      initial={{ name, description: data?.description ?? "" }}
      onSave={onSave}
      onCancel={onCancel}
      isSaving={isSaving}
    />
  );
}

function LocationForm({
  initial,
  onSave,
  onCancel,
  isSaving,
}: LocationFormProps) {
  const { t } = useTranslation(["equipment", "common"]);
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [parentId, setParentId] = useState("");

  return (
    <Card className="p-4 border-primary-200 dark:border-primary-800">
      <div className="space-y-3">
        <div>
          <Input
            label={t("locations.name")}
            required
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("locations.namePlaceholder")}
          />
        </div>
        <div>
          <Input
            label={t("locations.description")}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={t("locations.descriptionPlaceholder")}
          />
        </div>
        <LocationCombobox
          scope={{ moduleScope: "equipment" }}
          value={parentId}
          onChange={setParentId}
          id="equipment-location-parent"
          label={t("locations.parent")}
          placeholder={t("locations.parentNone")}
          searchPlaceholder={t("common:search")}
          emptyMessage={t("common:noResults")}
          clearable
          clearLabel={t("locations.parentNone")}
        />
        <div className="flex gap-2 justify-end pt-1">
          <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
            {t("common:form.cancel")}
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={isSaving || !name.trim()}
            onClick={() => onSave(name.trim(), description.trim(), parentId)}
          >
            {t("locations.save")}
          </Button>
        </div>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function EquipmentLocationsPage() {
  const { t } = useTranslation(["equipment", "locations", "common"]);
  const { setHeader } = useModulePageHeader();
  // Locations are Core storages, and `locations:write` is the key the API
  // checks on the other end of these buttons.
  const canWrite = useCanWrite("locations");
  const queryClient = useQueryClient();

  // The screen is called "Equipment Locations", so that is what it lists.
  // Not a context_tag filter: an asset can stand in an untagged location and
  // most of them do, so the scope is the union the API resolves — tagged for
  // this module, or holding its records. Listing the whole organization is
  // how Delete came to be offered on a walk-in cooler from the IT screen.
  const [showAddForm, setShowAddForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  // A page of them at a time, the search answered by the server: name, path
  // and short code are the three things a reader has to go on. The path
  // matters most — with thirty-odd rows, "Shelf 3" is unfindable and
  // "Warsaw office / Server room / Shelf 3" is not.
  const needle = useDebounce(search.trim(), 300);
  const {
    data: pages,
    isLoading,
    isError,
    refetch,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
  } = useLocationPages(
    { moduleScope: "equipment" },
    { search: needle, counts: true },
  );
  const locations = pages?.pages.flatMap((page) => page.items) ?? [];
  const found = pages?.pages[0]?.total ?? 0;

  useEffect(() => {
    if (showAddForm) return;
    setHeader({
      actions: canWrite ? (
        <div className="ml-auto w-full sm:w-auto">
          <Button
            leftIcon={<Plus size={16} />}
            onClick={() => setShowAddForm(true)}
            className="w-full sm:w-auto"
          >
            {t("locations.addTitle")}
          </Button>
        </div>
      ) : undefined,
    });
  }, [t, setHeader, showAddForm, canWrite]);

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.storages.all });

  const createMutation = useCreateStorageHierarchy(t("locations.createFailed"));

  const updateMutation = useUpdateStorage(t("locations.updateFailed"));

  const deleteMutation = useDeleteStorage(t("locations.deleteFailed"));

  const { confirm, confirmDialogProps } = useConfirm();

  // Location is a required field of every record standing in one, so the API
  // refuses to delete a location that holds anything. The screen used to ask
  // anyway and report a bare "Failed to delete" afterwards; it says so before
  // the click instead, which is how the rest of the application refuses.
  //
  // Two questions live on a row, and folding them into one number is how the
  // count under an IT screen's title came to include the organization's
  // groceries. The headline count is the module's own — the backend narrows
  // the listing's counts to it. The delete button answers to a different
  // number: the server refuses while any module's record stands HERE, and
  // only here — children are reparented on delete, not asked first — so the
  // guard reads the all-modules direct total, and the row shows it whenever
  // it is not already the same as the equipment count. The fallback chain
  // only keeps payloads from before each field existed refusing on the
  // conservative side.
  const equipmentHere = (loc: StorageLocationSummary) => loc.items_count ?? 0;
  const equipmentSubtree = (loc: StorageLocationSummary) =>
    loc.subtree_items_count ?? loc.items_count ?? 0;
  const recordsBlockingDelete = (loc: StorageLocationSummary) =>
    loc.total_items_count ?? loc.subtree_items_count ?? loc.items_count ?? 0;
  // Decision, vs the spaces module answering the same rows: spaces serves
  // the SAME core delete — reachable from its edit sheet — and adds an
  // archive beside it, its dialog naming the moved products, the children
  // that move up a level and the archive. Equipment keeps the core verb
  // alone: the doors were never the disagreement, the silence was. A
  // delete with a subtree is a tree rebuild, and the confirmation now
  // says so before the click — one flowing paragraph, both numbers
  // counted on the server from the full organization tree.
  //
  // The two sentences about the rebuild are CORE keys (`locations:edit.…`),
  // not equipment's: one operation, one sentence, read identically from the
  // equipment screen and from the spaces sheet. Equipment's own copies were
  // removed in the same change — a sentence kept in two files is a mirror
  // no gate compares, and the i18n plural snapshot exists because one such
  // family of forms had already drifted apart unnoticed.
  const handleDelete = async (loc: StorageLocationSummary) => {
    const message =
      t("locations.confirmDelete", { name: loc.name }) +
      locationDeleteConsequences(t, loc);
    const ok = await confirm({
      title: t("locations.deleteTitle", "Delete location"),
      message,
      variant: "danger",
      confirmLabel: t("common:actions.delete"),
    });
    if (!ok) return;
    deleteMutation.mutate(loc.id, {
      onSuccess: () => {
        toast.success(t("locations.deleted"));
        invalidate();
      },
    });
  };

  return (
    <div className="space-y-6">
      <ReadOnlyNotice module="locations" />
      {/* Add form */}
      {showAddForm && canWrite && (
        <div className="mb-4">
          <LocationForm
            onSave={(name, description, parentId) =>
              createMutation.mutate(
                {
                  parent_id: parentId || undefined,
                  steps: [{ name }],
                  description: description || undefined,
                  context_tag: "equipment",
                  context_schema: [],
                },
                {
                  onSuccess: () => {
                    toast.success(t("locations.created"));
                    setShowAddForm(false);
                    invalidate();
                  },
                },
              )
            }
            onCancel={() => setShowAddForm(false)}
            isSaving={createMutation.isPending}
          />
        </div>
      )}

      {/* List */}
      {(locations.length > 0 || needle) && (
        <ListControlBar
          search={{
            value: search,
            onChange: setSearch,
            placeholder: t("locationsPage.search"),
          }}
          resultCount={needle ? found : undefined}
        />
      )}

      {isError ? (
        <QueryError onRetry={() => refetch()} />
      ) : isLoading ? (
        <LoadingSpinner />
      ) : !needle && locations.length === 0 && !showAddForm ? (
        <EmptyState
          icon={MapPin}
          title={t("locationsPage.empty")}
          description={t("locationsPage.emptyDescription")}
          primaryAction={
            canWrite ? (
              <EmptyStateAction
                // Outline: the header's add is the view's one filled action,
                // and the same label filled twice read as two competing
                // first moves.
                variant="outline"
                label={t("locations.addTitle")}
                onClick={() => setShowAddForm(true)}
                leftIcon={Plus}
              />
            ) : undefined
          }
        />
      ) : locations.length === 0 ? (
        <p className="text-sm text-on-muted text-center py-8">
          {t("locationsPage.noResults")}
        </p>
      ) : (
        <div className="space-y-2">
          {locations.map((loc) =>
            editingId === loc.id ? (
              <EditingLocationForm
                key={loc.id}
                id={loc.id}
                name={loc.name}
                onSave={(name, description) =>
                  updateMutation.mutate(
                    {
                      id: loc.id,
                      data: { name, description: description || null },
                    },
                    {
                      onSuccess: () => {
                        toast.success(t("locations.updated"));
                        setEditingId(null);
                        invalidate();
                      },
                    },
                  )
                }
                onCancel={() => setEditingId(null)}
                isSaving={updateMutation.isPending}
              />
            ) : (
              // tighter rows on phones (85 px → ~69 px) so more
              // locations fit the first screen; desktop keeps p-4.
              <Card key={loc.id} className="p-3 sm:p-4">
                <CardContent className="p-0">
                  <div className="flex items-center gap-4">
                    <div className="flex-shrink-0 w-9 h-9 rounded-lg bg-primary-50 dark:bg-primary-900/30 flex items-center justify-center">
                      <MapPin size={18} className="text-primary-500" />
                    </div>
                    {/* flex container so name and code stack with a gap
                        instead of gluing into "Office BuildingSEED-SPH2". */}
                    <div className="flex-1 min-w-0 flex flex-col">
                      {/* The count the row already shows is the promise:
                          "N assets here" has to lead somewhere — and the
                          gate is the HERE count, the same one the asset
                          list answers for, so the link never promises more
                          than the list delivers. Locations holding nothing
                          themselves keep a plain name. */}
                      {equipmentHere(loc) > 0 ? (
                        <Link
                          to={`/equipment/assets?location=${loc.id}`}
                          className="flex items-center min-h-11 md:min-h-8 font-medium text-sm text-on hover:text-primary-600 hover:underline rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-400"
                          title={t("locations.view_assets")}
                          aria-label={`${loc.name} — ${t("locations.view_assets")}`}
                        >
                          {loc.name}
                        </Link>
                      ) : (
                        <span className="font-medium text-sm text-on">
                          {loc.name}
                        </span>
                      )}
                      <span className="flex items-center gap-2 flex-wrap">
                        {loc.context_tag === "equipment" && (
                          <span className="inline-flex items-center px-1.5 py-px rounded-md bg-accent-50 text-accent-700 border border-accent-200 dark:bg-accent-900/40 dark:text-accent-200 dark:border-accent-800 text-[10px] font-medium uppercase tracking-wide">
                            {t("locationsPage.equipmentTag", "Equipment")}
                          </span>
                        )}
                        {/* The counts speak for what the screen lists. When
                            "here" and "in the subtree" differ, both are
                            named — a parent row is where the two numbers
                            drift apart and the reader should see it. */}
                        {equipmentSubtree(loc) > 0 &&
                          (equipmentHere(loc) === equipmentSubtree(loc) ? (
                            <span className="text-[10px] text-on-muted">
                              {t("locations.holding", {
                                count: equipmentSubtree(loc),
                              })}
                            </span>
                          ) : (
                            <span className="text-[10px] text-on-muted">
                              {t("locations.holdingHereAndBelow", {
                                here: equipmentHere(loc),
                                below: equipmentSubtree(loc),
                              })}
                            </span>
                          ))}
                        {recordsBlockingDelete(loc) > equipmentHere(loc) && (
                          <span className="text-[10px] text-on-muted">
                            {t("locations.holdingTotal", {
                              count: recordsBlockingDelete(loc),
                            })}
                          </span>
                        )}
                      </span>
                      {locationPathBelowName(loc) && (
                        <p className="text-xs text-on-muted mt-0.5 truncate">
                          {locationPathBelowName(loc)}
                        </p>
                      )}
                      {loc.short_code && (
                        <span className="text-xs font-mono text-on-muted">
                          {loc.short_code}
                        </span>
                      )}
                    </div>
                    {canWrite && (
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => setEditingId(loc.id)}
                          aria-label={t("common:a11y.editNamed", {
                            name: loc.name,
                          })}
                        >
                          <Pencil size={16} />
                        </Button>
                        <Button
                          variant="ghostDanger"
                          size="icon"
                          onClick={() => handleDelete(loc)}
                          disabled={
                            deleteMutation.isPending ||
                            recordsBlockingDelete(loc) > 0
                          }
                          title={
                            recordsBlockingDelete(loc) > 0
                              ? t("locations.cannotDeleteHolding", {
                                  count: recordsBlockingDelete(loc),
                                })
                              : undefined
                          }
                          aria-label={
                            recordsBlockingDelete(loc) > 0
                              ? t("locations.cannotDeleteHolding", {
                                  count: recordsBlockingDelete(loc),
                                })
                              : t("common:a11y.deleteNamed", {
                                  name: loc.name,
                                })
                          }
                        >
                          <Trash2 size={16} />
                        </Button>
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>
            ),
          )}
          {hasNextPage && (
            <div className="flex justify-center pt-2">
              <Button
                variant="outline"
                onClick={() => void fetchNextPage()}
                disabled={isFetchingNextPage}
              >
                {t("locationsPage.showMore")}
              </Button>
            </div>
          )}
        </div>
      )}
      <ConfirmDialog {...confirmDialogProps} />
    </div>
  );
}
