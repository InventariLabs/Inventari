import { act, type ReactElement } from "react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import type { PageHeaderData } from "@/hooks/useModulePageHeader";
import type { PutawayRule } from "@/modules/warehouse/api/putaway";
import PutawayRulesPage from "./PutawayRulesPage";

const m = vi.hoisted(() => ({
  header: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
  refetch: vi.fn(),
  dialog: {} as Record<string, unknown>,
  rules: {
    data: [] as unknown[] | undefined,
    isError: false,
    isLoading: false,
  },
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock("@/hooks/useModulePageHeader", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useModulePageHeader")>()),
  useModulePageHeader: () => ({ setHeader: m.header }),
}));

vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => true,
  useCanManage: () => true,
}));

vi.mock("@/modules/shared/hooks/useCategories", () => ({
  useScopedCategories: () => ({ scoped: [] }),
}));

vi.mock("@/module-sdk", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/module-sdk")>()),
  useLocationOffer: () => ({ total: 3 }),
}));

vi.mock("@/modules/warehouse/hooks/usePutawayRules", () => ({
  usePutawayRules: () => ({
    ...m.rules,
    error: m.rules.isError ? new Error("boom") : null,
    refetch: m.refetch,
  }),
  useCreatePutawayRule: () => ({ mutate: m.create, isPending: false }),
  useUpdatePutawayRule: () => ({ mutate: m.update, isPending: false }),
  useDeletePutawayRule: () => ({ mutate: m.remove, isPending: false }),
}));

vi.mock("@/modules/warehouse/components/SilencedHomeShelves", () => ({
  SilencedHomeShelves: () => null,
}));

vi.mock("@/modules/warehouse/components/PutawayRuleEditorDialog", () => ({
  PutawayRuleEditorDialog: (props: Record<string, unknown>) => {
    for (const key of Object.keys(m.dialog)) delete m.dialog[key];
    Object.assign(m.dialog, props);
    return null;
  },
}));

function rule(over: Partial<PutawayRule> = {}): PutawayRule {
  return {
    id: "rule-1",
    organization_id: "org-1",
    product_template_id: null,
    category_id: null,
    context_tag: "frozen",
    location_type_code: null,
    target_location_id: "loc-1",
    target_location_name: "Freezer A",
    priority: 10,
    is_active: true,
    locations: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...over,
  } as unknown as PutawayRule;
}

function headerActions(): ReactElement {
  const calls = m.header.mock.calls;
  return (calls[calls.length - 1][0] as PageHeaderData).actions as ReactElement;
}

const payload = { context_tag: "frozen", target_location_id: "loc-2" };

/**
 * The rules list opens one editor for two jobs — a new rule and an edit —
 * and deletes behind a question. These catch an edit that creates a second
 * rule instead of updating the one pressed, an editor that opens on the
 * previous rule after Add, a delete that writes without asking or ignores a
 * "no", and a failed list that offers no way to ask again.
 */
describe("PutawayRulesPage — edit, add and delete", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    m.rules.data = [rule()];
    m.rules.isError = false;
    m.rules.isLoading = false;
  });

  it("updates the rule whose pencil was pressed, then closes the editor", async () => {
    const user = userEvent.setup();
    render(<PutawayRulesPage />);
    await user.click(
      screen.getByRole("button", { name: /^Edit Category group/ }),
    );
    expect(m.dialog.open).toBe(true);
    expect((m.dialog.rule as PutawayRule).id).toBe("rule-1");
    act(() => (m.dialog.onSubmit as (d: unknown) => void)(payload));
    expect(m.update).toHaveBeenCalledWith(
      { id: "rule-1", data: payload },
      expect.any(Object),
    );
    expect(m.create).not.toHaveBeenCalled();
    act(() => m.update.mock.calls[0][1].onSuccess());
    expect(toast.success).toHaveBeenCalledWith("Putaway rule updated");
    expect(m.dialog.open).toBe(false);
    expect(m.dialog.rule).toBeNull();
  });

  it("opens an empty editor from the header's Add and creates from it", async () => {
    const user = userEvent.setup();
    render(<PutawayRulesPage />);
    await user.click(
      screen.getByRole("button", { name: /^Edit Category group/ }),
    );
    act(() => (m.dialog.onClose as () => void)());
    render(headerActions());
    await user.click(screen.getByRole("button", { name: "Add Rule" }));
    expect(m.dialog.open).toBe(true);
    expect(m.dialog.rule).toBeNull();
    act(() => (m.dialog.onSubmit as (d: unknown) => void)(payload));
    expect(m.create).toHaveBeenCalledWith(payload, expect.any(Object));
  });

  it("deletes the rule only after the reader says yes", async () => {
    const user = userEvent.setup();
    render(<PutawayRulesPage />);
    await user.click(
      screen.getByRole("button", { name: /^Delete Category group/ }),
    );
    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    expect(m.remove).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(m.remove).toHaveBeenCalledWith("rule-1", expect.any(Object));
    act(() => m.remove.mock.calls[0][1].onSuccess());
    expect(toast.success).toHaveBeenCalledWith("Putaway rule removed");
  });

  it("deletes nothing when the reader backs out", async () => {
    const user = userEvent.setup();
    render(<PutawayRulesPage />);
    await user.click(
      screen.getByRole("button", { name: /^Delete Category group/ }),
    );
    await screen.findByRole("alertdialog");
    await user.keyboard("{Escape}");
    expect(m.remove).not.toHaveBeenCalled();
  });

  it("opens the editor for the first rule from the empty list", async () => {
    m.rules.data = [];
    const user = userEvent.setup();
    render(<PutawayRulesPage />);
    await user.click(
      screen.getByRole("button", { name: "Create your first rule" }),
    );
    expect(m.dialog.open).toBe(true);
    expect(m.dialog.rule).toBeNull();
  });

  it("asks for the list again from the failure", async () => {
    m.rules.isError = true;
    m.rules.data = undefined;
    const user = userEvent.setup();
    render(<PutawayRulesPage />);
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(m.refetch).toHaveBeenCalledTimes(1);
  });
});
