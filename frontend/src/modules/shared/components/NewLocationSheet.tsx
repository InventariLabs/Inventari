import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import type { StorageLocation } from "@/types";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { LocationCombobox } from "@/module-sdk";
import {
  Sheet,
  SheetActions,
  SheetBody,
  SheetFooter,
  SheetHeader,
} from "@/components/ui/Sheet";
import { queryKeys } from "@/hooks/queries/keys";
import { useCreateStorage } from "@/modules/shared/hooks/useStorageMutations";
import { useExistingLocations } from "@/modules/shared/hooks/useExistingLocations";
import { useLocationOffer, useLocationsById } from "@/module-sdk";
import { useWizardSuggestions } from "@/modules/shared/hooks/useWizardSuggestions";

interface NewLocationSheetProps {
  open: boolean;
  onClose: () => void;
  /** Called with the location just created; the caller picks it. */
  onCreated?: (storage: StorageLocation) => void;
  /** What the reader had typed into the picker's search, if anything. */
  initialName?: string;
}

/**
 * A new location, made from inside the form that needs one.
 *
 * The product form's location picker used to have one way out when the place
 * was not on the list: a link to the Storages screen in another tab, and a
 * reload of the form on return. A location is a name and, optionally, the
 * place it stands in — both fit here, with the storage wizard's name chips
 * for the reader who has not decided what to call it. Anything more (codes,
 * tracking fields) stays on the location's own screen.
 */
export function NewLocationSheet({
  open,
  onClose,
  onCreated,
  initialName = "",
}: NewLocationSheetProps) {
  const { t } = useTranslation(["locations", "common"]);
  const [name, setName] = useState(initialName);
  const [parentId, setParentId] = useState("");
  const createStorage = useCreateStorage();
  const queryClient = useQueryClient();
  // The same list the location pickers offer: a parent the reader could not
  // pick for a product is not a place to hang a new one under either.
  const offer = useLocationOffer({ purpose: "general" });
  const existing = useExistingLocations(parentId || null);
  const parent = useLocationsById(parentId ? [parentId] : []).byId.get(
    parentId,
  );
  const { locationSuggestions, filteredParentSuggestions } =
    useWizardSuggestions(existing.rows, parent);
  // Under a chosen place the chips name what stands inside it; at the top
  // level they name places themselves — the wizard's two steps in one field.
  const suggestions = parent ? locationSuggestions : filteredParentSuggestions;

  // Opened to type a name, so the name field takes the focus — after the
  // sheet's own focus trap has placed it, the way the storage wizard does.
  const nameRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!open) return;
    setName(initialName);
    setParentId("");
    const timer = setTimeout(() => nameRef.current?.focus(), 50);
    return () => clearTimeout(timer);
  }, [open, initialName]);

  // `mutate`, not `mutateAsync`: a refusal (a duplicate name under the same
  // parent) is the mutation's toast to show, and the sheet stays open with
  // what was typed.
  const submit = () => {
    const trimmed = name.trim();
    if (!trimmed || createStorage.isPending) return;
    createStorage.mutate(
      { name: trimmed, parent_id: parentId || null },
      {
        onSuccess: async (storage) => {
          toast.success(t("locations:addNew.created"));
          onClose();
          // The pick waits for the list that holds it: a form drops a chosen
          // location its picker does not offer, and handed the new one before
          // the refetch landed, the product form emptied the field again.
          await queryClient.invalidateQueries({
            queryKey: queryKeys.storages.all,
          });
          onCreated?.(storage as StorageLocation);
        },
      },
    );
  };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      maxWidth="sm"
      zIndex="modal-nested"
      aria-label={t("locations:addNew.title")}
    >
      <SheetHeader title={t("locations:addNew.title")} onClose={onClose} />
      <SheetBody className="p-5 space-y-4">
        <Input
          label={t("locations:addNew.nameLabel")}
          ref={nameRef}
          value={name}
          onChange={(event) => setName(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              submit();
            }
          }}
          placeholder={t("locations:addNew.namePlaceholder")}
        />
        {suggestions.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {suggestions.map((s) => (
              <Button
                key={s}
                type="button"
                variant={name === s ? "secondary" : "outline"}
                size="sm"
                onClick={() => setName(s)}
              >
                {s}
              </Button>
            ))}
          </div>
        )}
        {(offer.total ?? 0) > 0 && (
          <LocationCombobox
            id="new-location-parent"
            scope={{ purpose: "general" }}
            label={t("locations:addNew.parentLabel")}
            title={t("locations:addNew.parentLabel")}
            value={parentId}
            onChange={setParentId}
            placeholder={t("locations:addNew.parentPlaceholder")}
            searchPlaceholder={t("common:search")}
            emptyMessage={t("common:noResults")}
            clearable
            layer="confirm"
          />
        )}
      </SheetBody>
      <SheetFooter>
        <SheetActions>
          <Button type="button" variant="ghost" onClick={onClose}>
            {t("common:actions.cancel")}
          </Button>
          <Button
            type="button"
            onClick={submit}
            disabled={!name.trim() || createStorage.isPending}
          >
            {t("common:actions.save")}
          </Button>
        </SheetActions>
      </SheetFooter>
    </Sheet>
  );
}
