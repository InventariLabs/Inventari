import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { renderWithProviders } from "@/test/utils";
import { signInWith } from "@/test/auth";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { useArchivedItems } from "@/modules/inventory/hooks/useItems";
import { useOrganization } from "@/modules/settings/hooks/useOrganization";
import ArchivedItemsPage from "./ArchivedItemsPage";

type MutateOptions = { onSuccess?: () => void };

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
  restore: vi.fn(),
  purge: vi.fn(),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => mocks.navigate };
});

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/modules/inventory/hooks/useItems", () => ({
  useArchivedItems: vi.fn(),
}));

vi.mock("@/modules/inventory/hooks/useItemMutations", () => ({
  useRestoreItem: () => ({ mutate: mocks.restore, isPending: false }),
  usePurgeItem: () => ({ mutate: mocks.purge, isPending: false }),
}));

vi.mock("@/modules/settings/hooks/useOrganization", () => ({
  useOrganization: vi.fn(),
  useShowModuleData: vi.fn(() => false),
}));

function archiveOf(
  rows: { id: string; name: string }[],
): ReturnType<typeof useArchivedItems> {
  return {
    data: {
      items: rows.map((r) => ({
        ...r,
        deletion_reason: "EXPIRED",
        deleted_at: "2026-07-02T00:00:00Z",
        category: null,
      })),
      total: rows.length,
      limit: 50,
      offset: 0,
      has_more: false,
    },
    isLoading: false,
  } as unknown as ReturnType<typeof useArchivedItems>;
}

function serveArchive(rows: { id: string; name: string }[]) {
  vi.mocked(useArchivedItems).mockReturnValue(archiveOf(rows));
}

function renderPage() {
  return renderWithProviders(
    <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
      <ArchivedItemsPage />
    </PageHeaderContext.Provider>,
  );
}

function lastOptions(mock: ReturnType<typeof vi.fn>): MutateOptions {
  return mock.mock.calls.at(-1)?.[1] as MutateOptions;
}

/**
 * The archive's two writes go through a confirmation each. A restore that
 * sends the wrong row, a purge that drops the typed reason (or sends one made
 * of spaces), or a dialog that stays open after the write landed is the
 * reader confirming one thing and the server doing another.
 */
describe("ArchivedItemsPage — restore and purge go through their dialogs", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    signInWith(["items:read", "items:write", "items:purge"]);
    vi.mocked(useOrganization).mockReturnValue({
      data: { settings: { allow_permanent_delete: true } },
    } as unknown as ReturnType<typeof useOrganization>);
    serveArchive([
      { id: "a", name: "Old Bread" },
      { id: "b", name: "Milk" },
    ]);
  });

  it("restores the row whose button was pressed, after naming it", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getAllByRole("button", { name: "Restore" })[1]!);
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Milk")).toBeInTheDocument();
    expect(mocks.restore).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Restore" }));
    expect(mocks.restore).toHaveBeenCalledWith("b", expect.any(Object));

    act(() => lastOptions(mocks.restore).onSuccess?.());
    expect(toast.success).toHaveBeenCalledWith("Product restored");
    expect(await screen.findByText("Old Bread")).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("restores nothing when the dialog is cancelled", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getAllByRole("button", { name: "Restore" })[0]!);
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

    expect(mocks.restore).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("purges with the trimmed reason and empties the reason afterwards", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(
      screen.getAllByRole("button", { name: "Delete permanently" })[0]!,
    );
    const dialog = await screen.findByRole("alertdialog");
    await user.type(
      within(dialog).getByLabelText("Reason for permanent deletion"),
      "  test record  ",
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Delete permanently" }),
    );

    expect(mocks.purge).toHaveBeenCalledWith(
      { itemId: "a", reason: "test record" },
      expect.any(Object),
    );
    act(() => lastOptions(mocks.purge).onSuccess?.());
    expect(toast.success).toHaveBeenCalledWith("Product permanently deleted");
    expect(screen.queryByRole("alertdialog")).toBeNull();

    // The next purge starts from an empty reason, not the last one's.
    await user.click(
      screen.getAllByRole("button", { name: "Delete permanently" })[1]!,
    );
    expect(
      within(await screen.findByRole("alertdialog")).getByLabelText(
        "Reason for permanent deletion",
      ),
    ).toHaveValue("");
  });

  it("sends no reason when only spaces were typed, and forgets a cancelled one", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(
      screen.getAllByRole("button", { name: "Delete permanently" })[0]!,
    );
    let dialog = await screen.findByRole("alertdialog");
    await user.type(
      within(dialog).getByLabelText("Reason for permanent deletion"),
      "stale",
    );
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await user.click(
      screen.getAllByRole("button", { name: "Delete permanently" })[1]!,
    );
    dialog = await screen.findByRole("alertdialog");
    const reason = within(dialog).getByLabelText(
      "Reason for permanent deletion",
    );
    expect(reason).toHaveValue("");
    await user.type(reason, "   ");
    await user.click(
      within(dialog).getByRole("button", { name: "Delete permanently" }),
    );

    expect(mocks.purge).toHaveBeenCalledWith(
      { itemId: "b", reason: undefined },
      expect.any(Object),
    );
  });

  it("leads from an empty archive back to the active list", async () => {
    serveArchive([]);
    const user = userEvent.setup();
    renderPage();

    await user.click(
      screen.getByRole("button", { name: "Go to active products" }),
    );
    expect(mocks.navigate).toHaveBeenCalledWith("/inventory/items");
  });

  it("clears a search that found nothing", async () => {
    // The server's answer follows the phrase it was handed: nothing for any.
    vi.mocked(useArchivedItems).mockImplementation((params) =>
      archiveOf(params?.search ? [] : [{ id: "b", name: "Milk" }]),
    );
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByPlaceholderText(/search archived/i), "zzz");
    await user.click(await screen.findByRole("button", { name: "Clear" }));

    expect(screen.getByPlaceholderText(/search archived/i)).toHaveValue("");
    expect(await screen.findByText("Milk")).toBeInTheDocument();
  });
});
