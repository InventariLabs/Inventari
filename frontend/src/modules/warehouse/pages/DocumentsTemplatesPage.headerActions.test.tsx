import { act, type ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { render, screen } from "@/test/utils";
import type { PageHeaderData } from "@/hooks/useModulePageHeader";
import DocumentsTemplatesPage from "./DocumentsTemplatesPage";

const m = vi.hoisted(() => ({
  header: vi.fn(),
  seed: vi.fn(),
  refetch: vi.fn(),
  refetchBuiltIns: vi.fn(),
  templates: [] as unknown[],
  failed: false,
  builtInsFailed: false,
  editor: undefined as Record<string, unknown> | undefined,
  preview: {} as Record<string, unknown>,
  empty: {} as Record<string, unknown>,
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({ setHeader: m.header }),
}));
vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => true,
  useCanManage: () => true,
}));

vi.mock("@/modules/shared/hooks/useDocumentTemplates", () => {
  const idle = () => ({ mutate: vi.fn(), isPending: false });
  return {
    useDocumentTemplates: () => ({
      data: m.failed ? undefined : m.templates,
      isLoading: false,
      isError: m.failed,
      error: m.failed ? new Error("boom") : null,
      refetch: m.refetch,
    }),
    useBuiltInTemplates: () => ({
      data: m.builtInsFailed ? undefined : [{ name: "Standard" }],
      isError: m.builtInsFailed,
      error: m.builtInsFailed ? new Error("boom") : null,
      refetch: m.refetchBuiltIns,
    }),
    useDeleteTemplate: idle,
    useSeedDefaultTemplates: () => ({ mutate: m.seed, isPending: false }),
    useRefreshTemplateCopy: idle,
    useExportTemplate: idle,
    useImportTemplate: idle,
  };
});

// The editor, the preview and the empty state have their own tests; here
// they record what the page handed them.
vi.mock("@/modules/shared/components/TemplateEditorModal", () => ({
  TemplateEditorModal: (p: Record<string, unknown>) => {
    m.editor = p;
    return null;
  },
}));
vi.mock("@/modules/shared/components/BuiltInTemplatePreview", () => ({
  BuiltInTemplatePreview: (p: Record<string, unknown>) => {
    Object.assign(m.preview, p);
    return null;
  },
}));
vi.mock("@/modules/shared/components/TemplatesEmptyState", () => ({
  TemplatesEmptyState: (p: Record<string, unknown>) => {
    Object.assign(m.empty, p);
    return null;
  },
}));
vi.mock("@/modules/shared/components/TemplateCard", () => ({
  TemplateCard: () => null,
}));

const template = {
  id: "tpl-1",
  name: "Our receipt",
  document_type: "IN",
  body_html: "<p/>",
  is_default: false,
};

function headerActions(): ReactElement {
  const calls = m.header.mock.calls;
  return (calls[calls.length - 1][0] as PageHeaderData).actions as ReactElement;
}

type Fn = (...args: unknown[]) => unknown;

/**
 * The header's three buttons and the empty screen's entry points. These
 * catch a "Copy the built-in layouts" that copies nothing, an "Import" that
 * never opens the file picker, an editor or preview that cannot be closed,
 * and failures that offer no way to ask again.
 */
describe("DocumentsTemplatesPage — header and entry points", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    m.templates = [template];
    m.failed = false;
    m.builtInsFailed = false;
    m.editor = undefined;
    for (const k of Object.keys(m.preview)) delete m.preview[k];
    for (const k of Object.keys(m.empty)) delete m.empty[k];
  });

  it("copies the built-in templates from the header", async () => {
    const user = userEvent.setup();
    render(<DocumentsTemplatesPage />);
    render(headerActions());
    await user.click(
      screen.getByRole("button", { name: "Copy the built-in layouts" }),
    );
    expect(m.seed).toHaveBeenCalledTimes(1);
  });

  it("opens the file picker from Import", async () => {
    const user = userEvent.setup();
    const { container } = render(<DocumentsTemplatesPage />);
    const picker = container.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    const click = vi.spyOn(picker, "click");
    render(headerActions());
    await user.click(screen.getByRole("button", { name: "Import template" }));
    expect(click).toHaveBeenCalledTimes(1);
  });

  it("opens an empty editor from Add, and closes it", async () => {
    const user = userEvent.setup();
    render(<DocumentsTemplatesPage />);
    render(headerActions());
    await user.click(screen.getByRole("button", { name: "Add Template" }));
    expect(m.editor).toBeDefined();
    expect(m.editor?.template).toBeUndefined();
    const close = m.editor?.onClose as Fn;
    m.editor = undefined;
    act(() => {
      close();
    });
    expect(m.editor).toBeUndefined();
  });

  it("asks for the templates again from the failure", async () => {
    m.failed = true;
    const user = userEvent.setup();
    render(<DocumentsTemplatesPage />);
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(m.refetch).toHaveBeenCalledTimes(1);
  });

  it("asks for the built-in layouts again when they failed", async () => {
    m.builtInsFailed = true;
    const user = userEvent.setup();
    render(<DocumentsTemplatesPage />);
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(m.refetchBuiltIns).toHaveBeenCalledTimes(1);
  });
});

describe("DocumentsTemplatesPage — nothing written yet", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    m.templates = [];
    m.failed = false;
    m.builtInsFailed = false;
    m.editor = undefined;
    for (const k of Object.keys(m.preview)) delete m.preview[k];
    for (const k of Object.keys(m.empty)) delete m.empty[k];
  });

  it("opens the built-in preview and closes it again", () => {
    render(<DocumentsTemplatesPage />);
    expect(m.preview.open).toBe(false);
    act(() => {
      (m.empty.onPreview as Fn)();
    });
    expect(m.preview.open).toBe(true);
    act(() => {
      (m.preview.onClose as Fn)();
    });
    expect(m.preview.open).toBe(false);
  });

  it("copies the built-ins and opens the editor from the empty screen", () => {
    render(<DocumentsTemplatesPage />);
    act(() => {
      (m.empty.onSeed as Fn)();
    });
    expect(m.seed).toHaveBeenCalledTimes(1);
    act(() => {
      (m.empty.onCreate as Fn)();
    });
    expect(m.editor?.template).toBeUndefined();
    expect(m.editor).toBeDefined();
  });
});
