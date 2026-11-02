import { useState } from "react";
import type { RecipeTagItem } from "@/modules/recipes/types/nutrition";
import { Button } from "@/components/ui/Button";

interface TagFilterChipsProps {
  allTags: RecipeTagItem[];
  selectedTags: string[];
  onToggleTag: (tag: string) => void;
  onClearTags: () => void;
  clearTagsText: string;
  showMoreText: string;
  showLessText: string;
}

/** cap the chip rows on small screens — long tag lists push the
 *  first recipe card below the fold, so collapse beyond this many chips. */
const VISIBLE_TAG_LIMIT = 8;

export function TagFilterChips({
  allTags,
  selectedTags,
  onToggleTag,
  onClearTags,
  clearTagsText,
  showMoreText,
  showLessText,
}: TagFilterChipsProps) {
  const [expanded, setExpanded] = useState(false);

  if (allTags.length === 0) return null;

  // A selected tag outside the collapsed window stays visible — hiding an
  // active filter would make the current result set look arbitrary.
  const beyondLimit = allTags
    .slice(VISIBLE_TAG_LIMIT)
    .filter((tagItem) => selectedTags.includes(tagItem.name));
  const visibleTags = expanded
    ? allTags
    : [...allTags.slice(0, VISIBLE_TAG_LIMIT), ...beyondLimit];

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {visibleTags.map((tagItem) => {
        const isActive = selectedTags.includes(tagItem.name);
        return (
          <Button
            type="button"
            key={tagItem.name}
            onClick={() => onToggleTag(tagItem.name)}
            variant="outline"
            size="contentSm"
            className={`px-2.5 py-1 rounded-full text-xs font-medium ${
              isActive
                ? "bg-primary-50 hover:bg-primary-50 border-primary-500 text-on"
                : "bg-surface-raised hover:bg-surface-raised border-border text-on-secondary hover:border-primary-200 hover:text-on"
            }`}
          >
            {tagItem.color && (
              <span
                className="w-2.5 h-2.5 rounded-full shrink-0"
                style={{ backgroundColor: tagItem.color }}
              />
            )}
            {tagItem.name}
            <span className="text-xs">{tagItem.count}</span>
          </Button>
        );
      })}
      {allTags.length > VISIBLE_TAG_LIMIT && (
        <Button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          variant="link"
          size="contentSm"
          className="min-h-11 md:min-h-0 min-w-11 md:min-w-0 px-0 ml-1 text-xs text-on-muted hover:text-on-secondary underline"
        >
          {expanded ? showLessText : showMoreText}
        </Button>
      )}
      {selectedTags.length > 0 && (
        <Button
          type="button"
          onClick={onClearTags}
          variant="link"
          size="contentSm"
          className="px-0 ml-1 text-xs text-on-muted hover:text-on-secondary underline min-h-11 md:min-h-0 min-w-11 md:min-w-0"
        >
          {clearTagsText}
        </Button>
      )}
    </div>
  );
}
