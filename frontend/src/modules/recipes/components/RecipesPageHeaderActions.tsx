import type { ReactNode } from "react";
import type { TFunction } from "i18next";
import { CheckSquare, FolderPlus, Plus, Tag, Upload } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { ActionMenu, type ActionMenuAction } from "@/components/ui/ActionMenu";

interface RecipesPageHeaderActionsProps {
  selectionMode: boolean;
  /** Whether the collection holds anything to select. */
  hasRecipes: boolean;
  /** Whether any tag exists to browse, colour or merge. */
  hasTags: boolean;
  t: TFunction;
  onToggleSelectionMode: () => void;
  onToggleTags: () => void;
  onToggleImport: () => void;
  onNewCollection: () => void;
  onNewRecipe: () => void;
  /**
   * Whether the account may write. Every tool in this bar ends in one, so a
   * reader gets no bar at all rather than a partly disabled one.
   */
  canWrite?: boolean;
}

/**
 * One secondary action: an icon and its name, from `sm` up. Four unlabelled
 * icons in a row make the reader guess four times and rank them by nothing;
 * `/maker` and `/inventory/items` both label theirs. On a phone there is no
 * room for four names, so these buttons give way to one "More actions" menu
 * that spells each of them out.
 *
 * The name is also on the button as `aria-label` and `title`.
 */
function SecondaryAction({
  label,
  icon,
  active,
  onClick,
}: {
  label: string;
  icon: ReactNode;
  active?: boolean;
  onClick: () => void;
}) {
  return (
    <Button
      variant={active ? "secondary" : "outline"}
      onClick={onClick}
      title={label}
      aria-label={label}
      aria-pressed={active}
      className="hidden gap-1.5 px-3 sm:inline-flex"
    >
      {icon}
      {label}
    </Button>
  );
}

/**
 * RecipesPageHeaderActions — header toolbar actions for the recipes list page
 * (module settings, tags manager, import, multi-select mode, new recipe).
 *
 * Three weights: the gear is the lightest thing here and stays a ghost icon,
 * the list's own tools are outlined, and creating a recipe is the one filled
 * button. They used to be four identical ghosts and a primary.
 *
 * Three of the tools only mean something once there is something to act on:
 * batch selection over zero recipes selects nothing, the tag manager over zero
 * tags opens onto its own empty state, and a collection over zero recipes is a
 * folder for nothing. All three return with the first row.
 */
export function RecipesPageHeaderActions({
  selectionMode,
  hasRecipes,
  hasTags,
  t,
  onToggleSelectionMode,
  onToggleTags,
  onToggleImport,
  onNewCollection,
  onNewRecipe,
  canWrite = true,
}: RecipesPageHeaderActionsProps) {
  if (!canWrite) return null;

  const tools: (ActionMenuAction & { active?: boolean })[] = [
    ...(hasTags
      ? [
          {
            id: "tags",
            label: t("recipes:tags_manager.title"),
            icon: <Tag size={16} />,
            onSelect: onToggleTags,
          },
        ]
      : []),
    {
      id: "import",
      label: t("recipes:import_export.import_title"),
      icon: <Upload size={16} />,
      onSelect: onToggleImport,
    },
    ...(hasRecipes
      ? [
          {
            id: "new-collection",
            label: t("recipes:collections.new_collection"),
            icon: <FolderPlus size={16} />,
            onSelect: onNewCollection,
          },
        ]
      : []),
    ...(hasRecipes || selectionMode
      ? [
          {
            id: "select",
            label: t("recipes:bulk.select_mode"),
            icon: <CheckSquare size={16} />,
            active: selectionMode,
            onSelect: onToggleSelectionMode,
          },
        ]
      : []),
  ];

  return (
    <div className="flex items-center gap-2 shrink-0 ml-auto">
      {/* A phone has no room for four names: the tools collapse into one menu
          that spells each out, beside the labelled primary action. */}
      <ActionMenu
        label={t("common:actions.more")}
        actions={tools}
        triggerClassName="sm:hidden border border-border"
      />
      {tools.map(({ id, label, icon, active, onSelect }) => (
        <SecondaryAction
          key={id}
          label={label}
          icon={icon}
          active={active}
          onClick={onSelect}
        />
      ))}
      <Button onClick={onNewRecipe} leftIcon={<Plus size={16} />}>
        {t("recipes:actions.new_recipe")}
      </Button>
    </div>
  );
}
