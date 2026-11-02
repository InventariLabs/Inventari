import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Merge } from "lucide-react";
import { Sheet, SheetBody, SheetHeader } from "@/components/ui/Sheet";
import { Button } from "@/components/ui/Button";
import { useRecipeTags } from "../hooks/useRecipes";
import TagManager from "./TagManager";

interface TagsPanelProps {
  isOpen: boolean;
  onClose: () => void;
  onTagClick: (name: string) => void;
  titleText: string;
}

export function TagsPanel({
  isOpen,
  onClose,
  onTagClick,
  titleText,
}: TagsPanelProps) {
  const { t } = useTranslation(["recipes", "common"]);
  // The merge form lives in TagManager, but its toggle belongs next to the
  // panel title — so the open state is owned here.
  const [mergeOpen, setMergeOpen] = useState(false);
  // Same cached query TagManager reads — merging needs something to merge
  // away, so the toggle waits for the first tag.
  const hasTags = (useRecipeTags().data ?? []).length > 0;

  if (!isOpen) return null;

  return (
    <Sheet open={isOpen} onClose={onClose} aria-label={titleText}>
      <SheetHeader
        title={titleText}
        onClose={onClose}
        closeLabel={t("common:a11y.close")}
        className="px-5 py-3.5"
      >
        {hasTags && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setMergeOpen((v) => !v)}
            className="ml-auto mr-1"
          >
            <Merge size={16} />
            {t("recipes:tags_manager.merge_title")}
          </Button>
        )}
      </SheetHeader>
      <SheetBody className="px-5 pb-5">
        <TagManager
          mergeOpen={mergeOpen}
          onMergeDone={() => setMergeOpen(false)}
          onTagClick={(name) => {
            onTagClick(name);
            onClose();
          }}
        />
      </SheetBody>
    </Sheet>
  );
}
