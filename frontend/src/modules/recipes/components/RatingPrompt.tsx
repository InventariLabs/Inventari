import { useState } from "react";
import { Star } from "lucide-react";
import type { TFunction } from "i18next";
import { Button } from "@/components/ui/Button";
import {
  Sheet,
  SheetActions,
  SheetBody,
  SheetTitle,
} from "@/components/ui/Sheet";
import { cn } from "@/lib/utils";

interface RatingPromptProps {
  open: boolean;
  recipeName: string;
  isSaving: boolean;
  onRate: (rating: number) => void;
  onSkip: () => void;
  t: TFunction;
}

/**
 * RatingPrompt — asks for a 1-5 star rating right after cooking a meal
 * plan entry. Bottom sheet on mobile, centered on desktop.
 */
export function RatingPrompt({
  open,
  recipeName,
  isSaving,
  onRate,
  onSkip,
  t,
}: RatingPromptProps) {
  const [rating, setRating] = useState(0);
  const [hover, setHover] = useState(0);

  const active = hover || rating;

  return (
    <Sheet
      open={open}
      onClose={onSkip}
      zIndex="confirm"
      maxWidth="md"
      aria-label={t("recipes:meal_planner.rate_title")}
    >
      <SheetBody className="p-5">
        <SheetTitle className="text-sm mb-1">
          {t("recipes:meal_planner.rate_title")}
        </SheetTitle>
        <p className="text-xs text-on-secondary mb-4 line-clamp-2">
          {recipeName}
        </p>

        <div className="flex items-center justify-center gap-1.5 mb-5">
          {[1, 2, 3, 4, 5].map((star) => (
            <Button
              key={star}
              type="button"
              variant="ghost"
              size="iconSm"
              onClick={() => setRating(star)}
              onMouseEnter={() => setHover(star)}
              onMouseLeave={() => setHover(0)}
              aria-label={t("recipes:meal_planner.rate_star", { value: star })}
              // Kept without a hover surface on purpose: pointing at
              // the third star fills the first three, so a grey square under
              // one of them would contradict what the row is showing. The
              // press feedback from the base class stays.
              className="hover:bg-transparent"
            >
              <Star
                size={16}
                className={cn(
                  "transition-colors",
                  star <= active
                    ? "text-amber-400 fill-amber-400"
                    : "text-on-muted",
                )}
              />
            </Button>
          ))}
        </div>

        <SheetActions>
          <Button variant="outline" onClick={onSkip} disabled={isSaving}>
            {t("recipes:meal_planner.rate_skip")}
          </Button>
          <Button
            onClick={() => rating > 0 && onRate(rating)}
            disabled={isSaving || rating === 0}
          >
            {t("recipes:meal_planner.rate_submit")}
          </Button>
        </SheetActions>
      </SheetBody>
    </Sheet>
  );
}
