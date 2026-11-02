import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Trash2, Edit2, ArrowRight, Check } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/Button";
import { ActionMenu } from "@/components/ui/ActionMenu";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Input } from "@/components/ui/Input";
import { cn } from "@/lib/utils";
import type { ShoppingList } from "@/modules/shopping_lists/types/shopping";
import type { ShoppingListPreview } from "@/modules/shopping_lists/hooks/useShoppingLists";
import { formatPercentLocale } from "@/utils/formatters";

interface ShoppingListCardProps {
  list: ShoppingList;
  stats: ShoppingListPreview;
  editingName: string | null;
  newName: string;
  /** Where the card leads — a URL, because the whole card is a link. */
  to: string;
  onSetNewName: (name: string) => void;
  onStartEditName: () => void;
  onSaveName: () => void;
  onDeleteRequest: () => void;
  /** Whether to offer renaming and deleting the list. */
  canWrite?: boolean;
}

export function ShoppingListCard({
  list,
  stats,
  editingName,
  newName,
  to,
  onSetNewName,
  onStartEditName,
  onSaveName,
  onDeleteRequest,
  canWrite = true,
}: ShoppingListCardProps) {
  const { t } = useTranslation("shopping_lists");
  const progress = stats.total > 0 ? (stats.purchased / stats.total) * 100 : 0;
  const rest = stats.total - stats.names.length;
  const isEditingName = editingName === list.id;

  return (
    <Card
      data-testid="shopping-list-card"
      hoverable
      className="group relative flex flex-col p-6 overflow-hidden border border-transparent hover:border-accent-100/50 focus-within:border-accent-200"
    >
      <div className="flex-1 flex flex-col">
        <div className="flex-1">
          {isEditingName ? (
            <div className="flex gap-2 mb-6">
              <Input
                aria-label={t("shopping_lists:card.editName")}
                value={newName}
                onChange={(e) => onSetNewName(e.target.value)}
                className="h-12"
                autoFocus
                onKeyDown={(e) => e.key === "Enter" && onSaveName()}
              />
              <Button
                variant="primary"
                size="icon"
                onClick={onSaveName}
                aria-label={t("card.saveName")}
              >
                <Check size={20} />
              </Button>
            </div>
          ) : (
            <>
              <div className="flex justify-between items-start mb-4">
                <div>
                  <h3 className="text-sm font-semibold text-on group-hover:text-accent-700 transition-colors leading-tight mb-1">
                    {/* The card's one destination, stretched over the card by
                        a pseudo-element (§2.3a). What it replaced was a
                        `<div onClick>` covering the top half: no role, no
                        focus, invisible to a screen reader, and hover on a
                        surface that only responded to a click on part of
                        itself. */}
                    <Link
                      to={to}
                      className="after:absolute after:inset-0 after:content-[''] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500/40 rounded-sm"
                    >
                      {list.name}
                    </Link>
                  </h3>
                  <div className="flex items-center gap-2">
                    <Badge
                      variant={progress === 100 ? "success" : "secondary"}
                      className="text-[10px]"
                    >
                      {stats.purchased} / {stats.total} {t("detail.purchased")}
                    </Badge>
                    {progress === 100 && (
                      <Badge variant="success" className="text-[10px]">
                        {t("completed")}
                      </Badge>
                    )}
                  </div>
                </div>
                {/* Above the overlay, or the trigger would be unreachable —
                    the stretched link covers everything below it.

                    Renaming and deleting act on the record, not on what the
                    reader is doing right now, so they belong behind the "⋯" —
                    the same place the recipe detail keeps deleting. Deleting a
                    list was a bare bin icon one pixel from the rename pencil. */}
                {canWrite && (
                  <div className="relative z-10">
                    <ActionMenu
                      label={t("card.actionsFor", { name: list.name })}
                      actions={[
                        {
                          id: "rename",
                          label: t("card.editName"),
                          icon: <Edit2 size={16} />,
                          onSelect: onStartEditName,
                        },
                        {
                          id: "delete",
                          label: t("card.deleteList"),
                          icon: <Trash2 size={16} />,
                          onSelect: onDeleteRequest,
                          destructive: true,
                        },
                      ]}
                    />
                  </div>
                )}
              </div>

              <div className="mt-6 flex items-center gap-2">
                <div className="flex-1 h-2 bg-surface-raised rounded-full overflow-hidden">
                  <div
                    className={`h-full transition-all duration-700 rounded-full ${progress === 100 ? "bg-accent-500" : "bg-accent-400"}`}
                    style={{ width: `${progress}%` }}
                  />
                </div>
                <span className="text-[10px] font-medium text-on-muted w-8 text-right">
                  {formatPercentLocale(Math.round(progress), 0)}
                </span>
              </div>
            </>
          )}
        </div>

        <div className="mt-8 flex items-center justify-between">
          {/* Four identical box glyphs in a row of overlapping circles said
              two false things at once: that the card knew nothing about what
              is on the list, and — being the shape of an avatar stack — that
              the circles were people. The names were in the same answer the
              counts came from. */}
          <p className="min-w-0 flex-1 pr-3 truncate text-xs text-on-muted">
            {stats.names.length > 0
              ? stats.names.join(", ")
              : t("card.emptyPreview")}
            {rest > 0 && (
              <span className="ml-1 font-semibold text-on-secondary">
                {t("card.morePreview", { count: rest })}
              </span>
            )}
          </p>
          {/* The same destination as the title, kept for the affordance it
              gives a pointer and hidden from assistive technology, which would
              otherwise hear the card announced twice (§2.3a). */}
          <Link
            to={to}
            tabIndex={-1}
            aria-hidden="true"
            className={cn(
              buttonVariants({ variant: "secondary", size: "contentSm" }),
              // Sentence case, medium weight: uppercase marks a column
              // header or a status, and a card whose loudest element is the
              // word "Open" has buried its own name.
              "relative z-10 h-10 px-5 text-xs font-medium bg-surface-card shadow-sm hover:bg-accent-600 hover:text-white transition-all duration-300",
            )}
          >
            {t("actions.open")}
            <ArrowRight size={14} />
          </Link>
        </div>
      </div>
    </Card>
  );
}
