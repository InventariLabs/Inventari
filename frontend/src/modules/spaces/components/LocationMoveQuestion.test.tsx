import { useState } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import userEvent from "@testing-library/user-event";
import { render, screen, waitFor } from "@/test/utils";
import {
  storagesApi,
  type StorageMoveScope,
  type StorageReorgOperation,
} from "@/lib/api/storages";
import { LocationMoveQuestion } from "./LocationMoveQuestion";
import { useMoveQuestion } from "@/modules/spaces/hooks/useMoveQuestion";

vi.mock("@/lib/api/storages", () => ({
  storagesApi: { reorg: vi.fn() },
}));

const reorg = vi.mocked(storagesApi.reorg);

const MOVE: StorageReorgOperation = {
  op: "move",
  id: "cold",
  parent_id: "pantry",
};

function scope(overrides: Partial<StorageMoveScope> = {}): StorageMoveScope {
  return {
    index: 0,
    id: "cold",
    name: "Cold Storage",
    locations_inside: 9,
    products: 165,
    from_path: "Main Warehouse",
    to_path: "Pantry Building",
    warehouse_changes: true,
    ...overrides,
  };
}

/** What a dry run answers: nothing applied, nothing refused, the moves. */
const preview = (moves: StorageMoveScope[]) => ({
  applied: false,
  created: {},
  rejections: [],
  moves,
});

/** Asks about *operations* on a click and shows what `ask` resolved to. */
function Harness({ operations }: { operations: StorageReorgOperation[] }) {
  const question = useMoveQuestion();
  const [answer, setAnswer] = useState<string>("pending");
  return (
    <>
      <button
        onClick={async () =>
          setAnswer(JSON.stringify(await question.ask(operations)))
        }
      >
        Save
      </button>
      <output>{answer}</output>
      <LocationMoveQuestion {...question.questionProps} />
    </>
  );
}

async function save(operations: StorageReorgOperation[] = [MOVE]) {
  render(<Harness operations={operations} />);
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
}

const answered = () => screen.getByRole("status").textContent;

describe("a moved location that holds stock asks whether it physically moved", () => {
  beforeEach(() => reorg.mockReset());

  it("states the scope and starts on a physical move when the warehouse changes", async () => {
    reorg.mockResolvedValue(preview([scope()]));

    await save();

    expect(reorg).toHaveBeenCalledWith([MOVE], { dryRun: true });
    expect(
      await screen.findByText(
        "You are moving Cold Storage with 9 locations inside and 165 products to Pantry Building.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("radio", { name: "It physically moved" }),
    ).toBeChecked();

    await userEvent.click(screen.getByRole("button", { name: "Move" }));

    await waitFor(() =>
      expect(JSON.parse(answered() ?? "")).toEqual([
        { ...MOVE, relocation: "physical" },
      ]),
    );
  });

  it("starts on a layout correction within one warehouse, and either can be chosen", async () => {
    reorg.mockResolvedValue(
      preview([
        scope({
          locations_inside: 0,
          products: 1,
          to_path: "Main Warehouse / Zone B",
          warehouse_changes: false,
        }),
      ]),
    );

    await save();

    expect(
      await screen.findByText(
        "You are moving Cold Storage with 1 product to Main Warehouse / Zone B.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("radio", { name: "I am only correcting the layout" }),
    ).toBeChecked();
    await userEvent.click(
      screen.getByRole("radio", { name: "It physically moved" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Move" }));

    await waitFor(() =>
      expect(JSON.parse(answered() ?? "")[0].relocation).toBe("physical"),
    );
  });

  it("moves an empty location without asking", async () => {
    reorg.mockResolvedValue(
      preview([scope({ locations_inside: 0, products: 0 })]),
    );

    await save();

    await waitFor(() => expect(JSON.parse(answered() ?? "")).toEqual([MOVE]));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("saves nothing when the question is backed out of", async () => {
    reorg.mockResolvedValue(preview([scope()]));

    await save();
    await userEvent.click(
      await screen.findByRole("button", { name: "Cancel" }),
    );

    await waitFor(() => expect(answered()).toBe("null"));
  });

  it("does not ask the server about a batch with no move", async () => {
    const create: StorageReorgOperation = {
      op: "create",
      temporary_id: "new_1",
      name: "Shelf C",
      parent_id: null,
    };

    await save([create]);

    await waitFor(() => expect(JSON.parse(answered() ?? "")).toEqual([create]));
    expect(reorg).not.toHaveBeenCalled();
  });
});
