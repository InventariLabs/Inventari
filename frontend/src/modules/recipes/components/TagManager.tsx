import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Pencil, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import {
  useRecipeTags,
  useSetTagColor,
  useMergeTags,
  useDeleteTag,
} from "../hooks/useRecipes";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { ActionMenu } from "@/components/ui/ActionMenu";
import { InlinePopover } from "./InlinePopover";
import { TagRenameDialog } from "./TagRenameDialog";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/utils";
import { extractApiError, isNotFoundError } from "@/lib/errors";
import type { RecipeTagItem } from "@/modules/recipes/types/nutrition";

const PRESET_COLORS = [
  "#ef4444",
  "#f97316",
  "#eab308",
  "#22c55e",
  "#06b6d4",
  "#3b82f6",
  "#8b5cf6",
  "#ec4899",
  "#64748b",
];

function TagRow({
  tag,
  onTagClick,
  onRename,
  onDelete,
}: {
  tag: RecipeTagItem;
  onTagClick?: (name: string) => void;
  onRename: (name: string) => void;
  onDelete: (name: string) => void;
}) {
  const { t } = useTranslation(["recipes", "common"]);
  const [showPicker, setShowPicker] = useState(false);

  const setColorMutation = useSetTagColor();

  const handleColorPick = async (color: string | null) => {
    try {
      await setColorMutation.mutateAsync({ name: tag.name, color });
      toast.success(t("tags_manager.color_saved"));
      setShowPicker(false);
    } catch (error) {
      // Nothing above this catch reports it: the picker stays open.
      toast.error(extractApiError(error, t("common:errors.actionFailed")));
    }
  };

  return (
    <div className="flex items-center gap-2 py-2 border-b border-border last:border-0">
      {/* Color swatch */}
      <InlinePopover
        open={showPicker}
        onOpenChange={setShowPicker}
        align="start"
        className="w-48 flex flex-wrap gap-1.5"
        trigger={
          <Button
            size="inline"
            variant="ghost"
            className={cn(
              "w-4 h-4 rounded-full border shrink-0 transition hover:scale-110 p-0",
              tag.color ? "border-border" : "border-dashed border-on-muted",
            )}
            style={tag.color ? { backgroundColor: tag.color } : undefined}
            aria-label={t("tags_manager.set_color")}
            title={t("tags_manager.set_color")}
          />
        }
      >
        {PRESET_COLORS.map((c) => (
          <Button
            key={c}
            size="iconSm"
            variant="ghost"
            onClick={() => handleColorPick(c)}
            aria-label={t("tags.pick_colour", { colour: c })}
            className="rounded-full border border-white hover:scale-110 transition"
            style={{ backgroundColor: c }}
          />
        ))}
        <Button
          size="iconSm"
          variant="ghost"
          onClick={() => handleColorPick(null)}
          className="rounded-full border border-border hover:bg-surface-raised flex items-center justify-center transition"
          aria-label={t("tags_manager.clear_color")}
          title={t("tags_manager.clear_color")}
        >
          <X size={16} className="text-on-muted" aria-hidden="true" />
        </Button>
      </InlinePopover>

      {/* Tag name + count */}
      <Button
        variant="ghost"
        onClick={() => onTagClick?.(tag.name)}
        className="flex-1 justify-start text-left text-sm text-on-secondary font-medium hover:text-on transition"
      >
        {tag.name}
      </Button>
      <Badge variant="secondary" className="text-xs">
        {t("tags_manager.count", {
          count: tag.count,
          defaultValue: `${tag.count}`,
        })}
      </Badge>
      {/* Tags are typed into a comma-separated field, so a typo used to be
          permanent: the panel could colour a tag and merge it into another,
          and nothing here renamed one or took it away. */}
      <ActionMenu
        label={t("common:actions.more")}
        actions={[
          {
            id: "rename",
            label: t("recipes:tags_manager.rename"),
            icon: <Pencil size={16} />,
            onSelect: () => onRename(tag.name),
          },
          {
            id: "delete",
            label: t("recipes:tags_manager.delete"),
            icon: <Trash2 size={16} />,
            destructive: true,
            onSelect: () => onDelete(tag.name),
          },
        ]}
      />
    </div>
  );
}

export default function TagManager({
  onTagClick,
  mergeOpen = false,
  onMergeDone,
}: {
  onTagClick?: (name: string) => void;
  /** Whether the merge form is expanded — owned by the panel header. */
  mergeOpen?: boolean;
  /** Called once a merge succeeds, so the header can collapse the form. */
  onMergeDone?: () => void;
}) {
  const { t } = useTranslation("recipes");
  const tagsQuery = useRecipeTags();
  const mergeMutation = useMergeTags();

  const deleteMutation = useDeleteTag();

  const [mergeFrom, setMergeFrom] = useState("");
  const [mergeInto, setMergeInto] = useState("");
  const [confirmMerge, setConfirmMerge] = useState(false);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  const tags = tagsQuery.data ?? [];

  /** Renaming is a merge into a name that does not exist yet — the backend
   *  has done exactly that since the merge endpoint was written; it just had
   *  no way in that said "rename". */
  const handleRename = async (name: string, next: string) => {
    setRenaming(null);
    try {
      const result = await mergeMutation.mutateAsync({
        old_tag: name,
        new_tag: next,
      });
      toast.success(
        t("tags_manager.rename_success", { count: result.updated_recipes }),
      );
    } catch (err) {
      toast.error(extractApiError(err, t("tags_manager.rename_failed")));
    }
  };

  const handleDelete = async (name: string) => {
    setDeleting(null);
    try {
      const result = await deleteMutation.mutateAsync(name);
      toast.success(
        t("tags_manager.delete_success", { count: result.updated_recipes }),
      );
    } catch (err) {
      toast.error(extractApiError(err, t("tags_manager.delete_failed")));
    }
  };

  const handleMerge = async () => {
    setConfirmMerge(false);
    if (!mergeFrom.trim() || !mergeInto.trim()) return;
    try {
      const result = await mergeMutation.mutateAsync({
        old_tag: mergeFrom.trim(),
        new_tag: mergeInto.trim(),
      });
      toast.success(
        t("tags_manager.merge_success", {
          count: result.updated_recipes,
        }),
      );
      setMergeFrom("");
      setMergeInto("");
      onMergeDone?.();
    } catch (err) {
      // The 404 used to be recognised by grepping axios' own sentence
      // ("Request failed with status code 404"), which is not a contract.
      if (isNotFoundError(err)) {
        toast.error(t("tags_manager.merge_not_found"));
      } else {
        toast.error(extractApiError(err, t("tags_manager.merge_failed")));
      }
    }
  };

  return (
    <div>
      {/* Merge form — the toggle sits in the panel header. It needs a tag to
          merge away, so it stays out of the way until there is one: the tool
          whose job is to clean up free text used to ask for free text over an
          empty list, and answer with "tag not found". */}
      {mergeOpen && tags.length > 0 && (
        <div className="py-3 border-b border-border space-y-2">
          <div className="flex gap-2">
            <NativeSelect
              wrapperClassName="flex-1"
              label={t("tags_manager.merge_from")}
              value={mergeFrom}
              onChange={(e) => setMergeFrom(e.target.value)}
            >
              <option value="">
                {t("tags_manager.merge_from_placeholder")}
              </option>
              {tags.map((tag) => (
                <option key={tag.name} value={tag.name}>
                  {tag.name}
                </option>
              ))}
            </NativeSelect>
            {/* Free text on purpose: merging into a name that does not exist
                yet is how a tag gets renamed. */}
            <Input
              wrapperClassName="flex-1"
              id="tag-merge-into"
              label={t("tags_manager.merge_into")}
              type="text"
              value={mergeInto}
              onChange={(e) => setMergeInto(e.target.value)}
              list="tag-names"
            />
          </div>
          <datalist id="tag-names">
            {tags.map((tag) => (
              <option key={tag.name} value={tag.name} />
            ))}
          </datalist>
          <Button
            variant="primary"
            size="sm"
            onClick={() => setConfirmMerge(true)}
            disabled={
              mergeMutation.isPending || !mergeFrom.trim() || !mergeInto.trim()
            }
          >
            {mergeMutation.isPending && (
              <Loader2 size={16} className="animate-spin mr-1" />
            )}
            {t("tags_manager.merge_submit")}
          </Button>
        </div>
      )}

      <ConfirmDialog
        open={confirmMerge}
        variant="warning"
        title={t("tags_manager.merge_confirm_title")}
        message={t("tags_manager.merge_confirm_message", {
          from: mergeFrom,
          to: mergeInto,
        })}
        confirmLabel={t("tags_manager.merge_submit")}
        onConfirm={handleMerge}
        onCancel={() => setConfirmMerge(false)}
      />

      {/* Tag list */}
      <div className="pb-2 relative">
        {tagsQuery.isLoading && (
          <div className="py-4 flex justify-center">
            <Loader2 size={18} className="animate-spin text-on-muted" />
          </div>
        )}
        {tagsQuery.isError && (
          <InlineQueryError
            error={tagsQuery.error}
            onRetry={() => void tagsQuery.refetch()}
          />
        )}
        {tags.length === 0 && !tagsQuery.isLoading && !tagsQuery.isError && (
          <p className="text-sm text-on-muted py-4">
            {t("tags_manager.no_tags")}
          </p>
        )}
        {tags.map((tag) => (
          <TagRow
            key={tag.name}
            tag={tag}
            onTagClick={onTagClick}
            onRename={setRenaming}
            onDelete={setDeleting}
          />
        ))}
      </div>

      <TagRenameDialog
        name={renaming}
        onCancel={() => setRenaming(null)}
        onConfirm={handleRename}
      />

      <ConfirmDialog
        open={deleting !== null}
        variant="danger"
        title={t("tags_manager.delete_confirm_title")}
        message={t("tags_manager.delete_confirm_message", { name: deleting })}
        confirmLabel={t("tags_manager.delete")}
        onConfirm={() => deleting && void handleDelete(deleting)}
        onCancel={() => setDeleting(null)}
      />
    </div>
  );
}
