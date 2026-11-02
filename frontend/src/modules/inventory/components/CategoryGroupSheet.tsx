import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Sheet, SheetBody, SheetHeader } from "@/components/ui/Sheet";
import { FormSheetFooter } from "@/components/ui/FormSheetFooter";
import { extractApiError } from "@/lib/errors";
import { useRenameCategoryGroup } from "@/modules/shared/hooks/useCategories";
import { categoryGroupLabel } from "@/modules/inventory/utils/categoryGroups";

interface CategoryGroupSheetProps {
  /** The stored value — a seeded code like `FRIDGE`, or a label somebody typed. */
  group: string;
  onClose: () => void;
  /** The group's new name, or null when it was taken off its categories. */
  onDone: (newName: string | null) => void;
}

/**
 * The one place a category group can be renamed or taken away.
 *
 * A group is not a record: it is a label repeated on every category that
 * carries it. So there was nowhere to rename one — the only route was to open
 * each category in turn, and the food profile seeds a dozen or more per
 * group.
 *
 * Removing a group is not a deletion and asks for no confirmation: the
 * categories stay exactly where they are and stop being grouped, which the
 * line beside the button says. Nesting a confirmation inside a sheet is also
 * how a dialog ends up unable to take a click. What it offers instead is the
 * way back: the toast carries an undo that puts the whole group back in one
 * request, since a removed group can no longer be picked in the filter.
 */
export function CategoryGroupSheet({
  group,
  onClose,
  onDone,
}: CategoryGroupSheetProps) {
  const { t } = useTranslation(["categories", "common"]);
  const label = categoryGroupLabel(t, group);
  const [draft, setDraft] = useState(label);
  const renameGroup = useRenameCategoryGroup();

  async function apply(newName: string | null) {
    try {
      const result = await renameGroup.mutateAsync({
        currentName: group,
        newName,
      });
      if (newName) {
        toast.success(t("groups_manage.renamed"));
      } else {
        toast.success(t("groups_manage.removed"), {
          action: {
            label: t("groups_manage.undo"),
            onClick: () => void restore(result.category_ids),
          },
        });
      }
      onDone(newName);
    } catch (error) {
      toast.error(extractApiError(error, t("groups_manage.error")));
    }
  }

  // The categories have no label left to be found by, so they are named by
  // the ids the removal returned.
  async function restore(categoryIds: string[]) {
    try {
      await renameGroup.mutateAsync({
        currentName: group,
        newName: group,
        categoryIds,
      });
      toast.success(t("groups_manage.restored"));
    } catch (error) {
      toast.error(extractApiError(error, t("groups_manage.error")));
    }
  }

  function save() {
    const typed = draft.trim();
    // The field is prefilled with what the reader sees, which for a seeded
    // group is its translation. Saving that untouched would replace a code
    // every language has a word for with one language's word.
    if (!typed || typed === label) {
      onClose();
      return;
    }
    void apply(typed);
  }

  return (
    <Sheet
      open
      onClose={onClose}
      maxWidth="sm"
      aria-label={t("groups_manage.manage")}
    >
      <SheetHeader
        title={t("groups_manage.title", { group: label })}
        onClose={onClose}
      />
      <SheetBody className="p-5 space-y-4">
        <div>
          <Input
            label={t("groups_manage.nameLabel")}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            autoFocus
          />
          <p className="mt-1.5 text-xs text-on-muted">
            {t("groups_manage.hint")}
          </p>
        </div>
        <div>
          <Button
            variant="ghostDanger"
            size="sm"
            onClick={() => void apply(null)}
            disabled={renameGroup.isPending}
          >
            {t("groups_manage.remove")}
          </Button>
          <p className="mt-1.5 text-xs text-on-muted">
            {t("groups_manage.removeMessage")}
          </p>
        </div>
      </SheetBody>
      <FormSheetFooter
        isPending={renameGroup.isPending}
        lineCount={0}
        cancelText={t("common:actions.cancel")}
        submitText={t("common:actions.save")}
        submitDisabled={!draft.trim()}
        onCancel={onClose}
        onSubmit={save}
      />
    </Sheet>
  );
}
