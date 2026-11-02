import PickingView from "./PickingView";
import CookingMode from "./CookingMode";
import { useState } from "react";
import type { RecipeIngredient } from "@/modules/recipes/types/core";

interface RecipeCookingFlowProps {
  recipeId: string;
  recipeName: string;
  instructions?: string | null;
  ingredients?: RecipeIngredient[];
  /** Servings the page is set to — what both screens work on. */
  activeServings: number;
  /** The recipe's own servings, for the picking screen's scale control. */
  baseServings: number;
  picking: boolean;
  cooking: boolean;
  onPickingClose: (completed?: boolean) => void;
  onCookingClose: () => void;
}

/**
 * The two screens one dinner runs through, and the thread between them.
 *
 * Picking the ingredients and then cooking them step by step is one meal,
 * so the cook continues the session the picking opened: without that thread
 * the meal was recorded twice — the picked run left unrated, and the note
 * hung on a second entry reading "nothing picked".
 */
export function RecipeCookingFlow({
  recipeId,
  recipeName,
  instructions,
  ingredients,
  activeServings,
  baseServings,
  picking,
  cooking,
  onPickingClose,
  onCookingClose,
}: RecipeCookingFlowProps) {
  const [pickedSessionId, setPickedSessionId] = useState<string | undefined>(
    undefined,
  );

  return (
    <>
      {picking && (
        <PickingView
          recipeId={recipeId}
          recipeName={recipeName}
          defaultServings={activeServings}
          baseServings={baseServings}
          ingredients={ingredients}
          onClose={(completed, sessionId) => {
            if (completed) setPickedSessionId(sessionId);
            onPickingClose(completed);
          }}
        />
      )}

      {cooking && instructions && (
        <CookingMode
          recipeId={recipeId}
          recipeName={recipeName}
          instructions={instructions}
          ingredients={ingredients}
          servings={activeServings}
          pickingSessionId={pickedSessionId}
          onSessionConsumed={() => setPickedSessionId(undefined)}
          onClose={onCookingClose}
        />
      )}
    </>
  );
}
