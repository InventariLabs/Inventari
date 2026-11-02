import { useState } from "react";
import {
  storagesApi,
  type StorageMoveScope,
  type StorageReorgOperation,
} from "@/lib/api/storages";

export type MoveRelocation = NonNullable<StorageReorgOperation["relocation"]>;

/** What the question shows: the moves that carry stock, and how to answer. */
export interface MoveQuestionProps {
  scopes: StorageMoveScope[] | null;
  onAnswer: (choices: Record<number, MoveRelocation>) => void;
  onCancel: () => void;
}

/**
 * Asks, before a batch of moves is saved, which of them physically happened.
 *
 * A move of a location that holds stock is either a correction of the layout
 * — the stock was always there — or a physical move, which records a move of
 * every product inside. The server is asked first what each move would carry
 * (a dry run of the same batch, read on its final tree); a batch whose moves
 * carry no stock, or one the server would refuse anyway, goes through as it
 * is, without a question nobody needs to answer.
 *
 * `ask` resolves to the operations with each answer on its move, or `null`
 * when the person moving backed out.
 */
export function useMoveQuestion() {
  const [pending, setPending] = useState<{
    scopes: StorageMoveScope[];
    resolve: (choices: Record<number, MoveRelocation> | null) => void;
  } | null>(null);

  const ask = async (
    operations: StorageReorgOperation[],
  ): Promise<StorageReorgOperation[] | null> => {
    if (!operations.some((op) => op.op === "move")) return operations;
    const preview = await storagesApi.reorg(operations, { dryRun: true });
    // A refused batch is reported by the save itself, reason by reason.
    if (preview.rejections.length > 0) return operations;
    const holding = preview.moves.filter((scope) => scope.products > 0);
    if (holding.length === 0) return operations;
    const choices = await new Promise<Record<number, MoveRelocation> | null>(
      (resolve) => setPending({ scopes: holding, resolve }),
    );
    setPending(null);
    if (!choices) return null;
    return operations.map((op, index) =>
      choices[index] ? { ...op, relocation: choices[index] } : op,
    );
  };

  const questionProps: MoveQuestionProps = {
    scopes: pending?.scopes ?? null,
    onAnswer: (choices) => pending?.resolve(choices),
    onCancel: () => pending?.resolve(null),
  };

  return { ask, questionProps };
}
