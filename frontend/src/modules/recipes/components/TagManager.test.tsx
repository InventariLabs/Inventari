import { afterEach, describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import TagManager from "./TagManager";
import type { RecipeTagItem } from "@/modules/recipes/types/nutrition";

let tags: RecipeTagItem[] = [];
const tagsRead = vi.hoisted(() => ({ failed: false, refetch: vi.fn() }));
const mergeMutate = vi.fn().mockResolvedValue({ updated_recipes: 3 });
const setColor = vi.fn();

vi.mock("../hooks/useRecipes", () => ({
  useRecipeTags: () => ({
    data: tagsRead.failed ? undefined : tags,
    isLoading: false,
    isError: tagsRead.failed,
    refetch: tagsRead.refetch,
  }),
  useSetTagColor: () => ({ mutateAsync: setColor, isPending: false }),
  useMergeTags: () => ({ mutateAsync: mergeMutate, isPending: false }),
  useDeleteTag: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const tag = (name: string): RecipeTagItem => ({ name, count: 2, color: null });

describe("TagManager merge form", () => {
  beforeEach(() => {
    mergeMutate.mockClear();
    tags = [tag("dinner"), tag("Dinner")];
  });

  it("stays away when there is no tag to merge", () => {
    tags = [];
    render(<TagManager mergeOpen />);

    expect(screen.queryByLabelText("Replace tag")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Merge" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("No tags yet")).toBeInTheDocument();
  });

  it("offers the existing tags instead of asking for free text", () => {
    render(<TagManager mergeOpen />);

    const from = screen.getByLabelText("Replace tag");
    expect(from.tagName).toBe("SELECT");
    expect(screen.getByRole("option", { name: "dinner" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Dinner" })).toBeInTheDocument();
  });

  it("asks before rewriting every recipe that carries the tag", async () => {
    render(<TagManager mergeOpen />);

    fireEvent.change(screen.getByLabelText("Replace tag"), {
      target: { value: "Dinner" },
    });
    fireEvent.change(screen.getByLabelText("With tag"), {
      target: { value: "dinner" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Merge" }));

    expect(mergeMutate).not.toHaveBeenCalled();
    expect(await screen.findByText("Merge tags?")).toBeInTheDocument();

    fireEvent.click(
      screen.getAllByRole("button", { name: "Merge" }).slice(-1)[0],
    );
    expect(mergeMutate).toHaveBeenCalledWith({
      old_tag: "Dinner",
      new_tag: "dinner",
    });

    // A merge that went through empties the form for the next one.
    await waitFor(() =>
      expect(screen.getByLabelText("With tag")).toHaveValue(""),
    );
  });
});

describe("TagManager when the tags did not load", () => {
  beforeEach(() => {
    tagsRead.failed = true;
    tagsRead.refetch.mockClear();
  });

  afterEach(() => {
    tagsRead.failed = false;
  });

  it("offers a retry instead of saying there are no tags yet", () => {
    render(<TagManager mergeOpen />);

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("No tags yet")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(tagsRead.refetch).toHaveBeenCalledTimes(1);
  });
});

describe("TagManager colour", () => {
  it("says why when the colour is refused", async () => {
    // Nothing above the picker reports it: the catch here used to say
    // "handled globally" and nothing was.
    tags = [tag("dinner")];
    setColor.mockRejectedValueOnce(new Error("refused"));
    render(<TagManager />);

    fireEvent.click(screen.getByRole("button", { name: "Set color" }));
    fireEvent.click(await screen.findByRole("button", { name: "Clear color" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "The action could not be completed.",
      ),
    );
  });
});

describe("TagManager rename", () => {
  beforeEach(() => {
    vi.mocked(toast.error).mockClear();
    tags = [tag("dinner")];
  });

  it("calls a failed rename a rename, not a merge", async () => {
    // A rename travels as a merge into a new name, but the reader asked to
    // rename — the failure must not talk about merging tags.
    mergeMutate.mockRejectedValueOnce(new Error("Request failed"));
    const user = userEvent.setup();
    render(<TagManager />);

    await user.click(screen.getByRole("button", { name: /more actions/i }));
    await user.click(await screen.findByRole("button", { name: "Rename" }));
    await user.clear(await screen.findByLabelText("New name"));
    await user.type(screen.getByLabelText("New name"), "supper");
    await user.click(
      screen.getAllByRole("button", { name: "Rename" }).slice(-1)[0],
    );

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Failed to rename the tag"),
    );
  });
});
