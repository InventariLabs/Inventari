import { useState } from "react";
import { SheetActions } from "@/components/ui/Sheet";
import { useTranslation } from "react-i18next";
import { MapPin, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { LocationCombobox } from "@/module-sdk";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/Dialog";
import { useCreateStorageHierarchy } from "@/modules/shared/hooks/useStorageMutations";
import { toast } from "sonner";
import { extractApiError } from "@/lib/errors";

interface QuickAddLocationModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreated: (id: string) => void;
}

export default function QuickAddLocationModal({
  isOpen,
  onClose,
  onCreated,
}: QuickAddLocationModalProps) {
  const { t } = useTranslation(["equipment", "common"]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [parentId, setParentId] = useState("");

  // ADR-018: any location can hold another, so the parent is searched among
  // all of them, not from the top level. The path under each name is what
  // tells two rooms called "Storage" apart. "All of them" stays the module's
  // own shelves — tagged for equipment, or already holding its records —
  // because an equipment location hangs under a place equipment stands, and
  // offering a walk-in cooler as its parent is how a laptop ends up in the
  // freezer.
  const createMutation = useCreateStorageHierarchy();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;

    createMutation.mutate(
      {
        parent_id: parentId || undefined,
        steps: [{ name: name.trim() }],
        description: description.trim() || undefined,
        context_tag: "equipment",
        context_schema: [],
      },
      {
        onSuccess: (created) => {
          toast.success(
            t("locations.created", "Location created successfully"),
          );
          onCreated(created.id);
          setName("");
          setDescription("");
          onClose();
        },
        onError: (err) => {
          toast.error(
            extractApiError(
              err,
              t("locations.createFailed", "Failed to create location"),
            ),
          );
        },
      },
    );
  };

  // Radix Dialog handles ESC, focus trap, scroll lock, and provides
  // the canonical z-modal token. The Radix-injected X button replaces the
  // legacy manual <X /> close button in the header — kept the title row
  // right-aligned by composing it with the icon + title only. The scroll
  // contract is retained: form body has min-h-0 flex-1 overflow-y-auto so the
  // action buttons always stay inside the viewport on small screens.
  return (
    <Dialog open={isOpen} onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        className="w-full max-w-md gap-0 p-0 rounded-t-3xl sm:rounded-2xl max-h-[90vh] flex flex-col overflow-hidden mx-0 sm:mx-4"
        data-testid="quick-location-modal-card"
      >
        <DialogHeader className="flex flex-row items-center gap-2 border-b border-border p-4">
          <div className="p-2 rounded-lg bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-500">
            <MapPin size={18} />
          </div>
          <DialogTitle className="text-base font-semibold text-on">
            {t("locations.addTitle", "Add Location")}
          </DialogTitle>
          <DialogDescription className="sr-only">
            {t("locations.addTitle", "Add Location")}
          </DialogDescription>
        </DialogHeader>

        <form
          data-testid="quick-location-modal-body"
          onSubmit={handleSubmit}
          className="min-h-0 flex-1 overflow-y-auto p-4 space-y-4"
        >
          <div>
            <Input
              label={t("locations.name", "Location name")}
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t(
                "locations.namePlaceholder",
                "e.g. Server Room, IT Storage",
              )}
            />
          </div>

          <div>
            <Input
              label={t("locations.description", "Description")}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t(
                "locations.descriptionPlaceholder",
                "Floor, building, details…",
              )}
            />
          </div>

          <LocationCombobox
            scope={{ moduleScope: "equipment" }}
            value={parentId}
            onChange={setParentId}
            id="quick-location-parent"
            label={t("locations.parent")}
            placeholder={t("locations.parentNone")}
            searchPlaceholder={t("common:search")}
            emptyMessage={t("common:noResults")}
            clearable
            clearLabel={t("locations.parentNone")}
          />

          <SheetActions className="pt-2">
            <Button
              type="button"
              variant="outline"
              onClick={onClose}
              disabled={createMutation.isPending}
            >
              {t("common:form.cancel", "Cancel")}
            </Button>
            <Button
              type="submit"
              disabled={!name.trim() || createMutation.isPending}
            >
              {createMutation.isPending ? (
                <Loader2 size={16} className="animate-spin mr-2" />
              ) : (
                <MapPin size={16} className="mr-2" />
              )}
              {t("locations.add", "Add")}
            </Button>
          </SheetActions>
        </form>
      </DialogContent>
    </Dialog>
  );
}
