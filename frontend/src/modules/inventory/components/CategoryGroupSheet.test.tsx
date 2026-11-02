import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { CategoryGroupSheet } from "./CategoryGroupSheet";
import { useRenameCategoryGroup } from "@/modules/shared/hooks/useCategories";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/modules/shared/hooks/useCategories", () => ({
  useRenameCategoryGroup: vi.fn(),
}));

const mutateAsync = vi.fn();
const onClose = vi.fn();
const onDone = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  mutateAsync.mockResolvedValue({ updated: 3 });
  vi.mocked(useRenameCategoryGroup).mockReturnValue({
    mutateAsync,
    isPending: false,
  } as unknown as ReturnType<typeof useRenameCategoryGroup>);
});

const open = (group: string) =>
  render(
    <CategoryGroupSheet group={group} onClose={onClose} onDone={onDone} />,
  );

describe("CategoryGroupSheet", () => {
  it("renames the group for every category carrying it, in one go", async () => {
    const user = userEvent.setup();
    open("Tools");

    const field = screen.getByLabelText("Group name");
    await user.clear(field);
    await user.type(field, "Workshop");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({
        currentName: "Tools",
        newName: "Workshop",
      }),
    );
    expect(onDone).toHaveBeenCalledWith("Workshop");
  });

  it("takes the group off its categories without deleting them", async () => {
    const user = userEvent.setup();
    open("Tools");

    await user.click(screen.getByRole("button", { name: /remove group/i }));

    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({
        currentName: "Tools",
        newName: null,
      }),
    );
    expect(onDone).toHaveBeenCalledWith(null);
  });

  it("offers an undo that puts the removed group back on the same categories", async () => {
    const user = userEvent.setup();
    mutateAsync.mockResolvedValue({ updated: 2, category_ids: ["a", "b"] });
    open("Tools");

    await user.click(screen.getByRole("button", { name: /remove group/i }));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(null));

    const options = vi.mocked(toast.success).mock.calls[0][1] as unknown as {
      action: { onClick: () => void };
    };
    options.action.onClick();

    await waitFor(() =>
      expect(mutateAsync).toHaveBeenLastCalledWith({
        currentName: "Tools",
        newName: "Tools",
        categoryIds: ["a", "b"],
      }),
    );
  });

  it("shows a seeded code under its translated name", () => {
    open("FREEZER");

    expect(screen.getByLabelText("Group name")).toHaveValue("Freezer");
  });

  it("does not turn a translated code into one language's word", async () => {
    // The field is prefilled with what the reader sees. Saving that untouched
    // would replace "FREEZER" — which every locale has a word for — with the
    // English one.
    const user = userEvent.setup();
    open("FREEZER");

    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(mutateAsync).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });
});
