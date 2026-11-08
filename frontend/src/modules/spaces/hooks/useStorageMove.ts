import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { storagesApi } from "@/lib/api/storages";
import type { StorageReorgOperation } from "@/lib/api/storages";
import { invalidation } from "@/lib/api/invalidation";
import { extractApiError, ReadableError } from "@/lib/errors";
import { useMoveQuestion } from "@/modules/spaces/hooks/useMoveQuestion";

export interface StorageMove {
  id: string;
  parent_id: string | null;
}

/**
 * Moving locations through the reorganization endpoint.
 *
 * The endpoint already applies a batch atomically; a move from this screen is
 * a batch of one (or one per selected row), so it needs no draft state and no
 * Save button. Undo is the same endpoint with the parent each location had
 * before, kept by the caller that still holds the old answer.
 */
export function useStorageMove() {
  const { t } = useTranslation(["locations", "common"]);
  const queryClient = useQueryClient();
  const moveQuestion = useMoveQuestion();
  const [isMoving, setIsMoving] = useState(false);

  // Where each location stood before the move, read when it is asked for:
  // the undo needs the answer from then, not a list the screen keeps.
  const parentsOf = async (
    ids: string[],
  ): Promise<Map<string, string | null>> => {
    const page = await storagesApi.getPage({
      ids,
      usage: "all",
      include_archived: true,
      counts: false,
      limit: Math.min(ids.length, 200),
    });
    return new Map(page.items.map((row) => [row.id, row.parent_id ?? null]));
  };

  const operationsFor = (moves: StorageMove[]): StorageReorgOperation[] =>
    moves.map((move) => ({
      op: "move",
      id: move.id,
      parent_id: move.parent_id,
    }));

  const apply = async (operations: StorageReorgOperation[]) => {
    const result = await storagesApi.reorg(operations);
    if (!result.applied) {
      // The server's reason is a sentence for the reader (it names the place
      // and the rule); a plain Error would be shown as the generic failure.
      throw new ReadableError(
        result.rejections[0]?.reason ?? t("locations:move.rejected"),
      );
    }
    invalidation.storages(queryClient);
  };

  const undo = async (before: StorageMove[]) => {
    try {
      await apply(operationsFor(before));
      toast.success(t("locations:move.undoDone"));
    } catch (error) {
      toast.error(extractApiError(error, t("locations:move.undoFailed")));
    }
  };

  const move = async (moves: StorageMove[]) => {
    if (moves.length === 0 || isMoving) return;
    setIsMoving(true);
    try {
      const parents = await parentsOf(moves.map((move) => move.id));
      const before = moves.map((move) => ({
        id: move.id,
        parent_id: parents.get(move.id) ?? null,
      }));
      // A location that holds stock is either carried somewhere or only
      // re-filed: the server's dry run says which moves carry products, and
      // backing out of the question moves nothing.
      const operations = await moveQuestion.ask(operationsFor(moves));
      if (!operations) return;
      await apply(operations);
      toast.success(t("locations:move.moved", { count: moves.length }), {
        action: {
          label: t("locations:move.undo"),
          onClick: () => void undo(before),
        },
      });
    } catch (error) {
      toast.error(extractApiError(error, t("locations:move.failed")));
    } finally {
      setIsMoving(false);
    }
  };

  return { move, isMoving, moveQuestion: moveQuestion.questionProps };
}
