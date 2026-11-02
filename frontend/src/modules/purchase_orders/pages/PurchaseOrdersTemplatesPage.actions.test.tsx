import { useCallback, useState } from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { onePage } from "@/test/mocks/page";
import { server } from "@/test/mocks/server";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import PurchaseOrdersTemplatesPage from "./PurchaseOrdersTemplatesPage";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => true,
  useCanManage: () => true,
}));

// The editor is the shared one with its own tests; here it only has to say
// which template it was opened on, and close.
vi.mock("@/modules/shared/components/TemplateEditorModal", () => ({
  TemplateEditorModal: (props: {
    template?: { name: string };
    onClose: () => void;
  }) => (
    <div role="dialog" aria-label="Template editor">
      <span>{props.template?.name ?? "new template"}</span>
      <button onClick={props.onClose}>close editor</button>
    </div>
  ),
}));

const TEMPLATE = {
  id: "tpl-1",
  organization_id: "org-1",
  module: "purchase_orders",
  name: "Supplier copy",
  document_type: "STANDARD",
  body_html: "<p>{{po_number}}</p>",
  is_default: false,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function PageHost() {
  const [data, setData] = useState<PageHeaderData>({});
  const setHeader = useCallback((next: PageHeaderData) => setData(next), []);
  return (
    <PageHeaderContext.Provider value={{ data, setHeader }}>
      <header aria-label="Page header">{data.actions}</header>
      <PurchaseOrdersTemplatesPage />
    </PageHeaderContext.Provider>
  );
}

let deleted: string[];
let seeded: number;

function serve(templates: unknown[]) {
  server.use(
    http.get("*/api/v1/purchase-orders/templates", () =>
      HttpResponse.json(onePage(templates)),
    ),
    http.delete("*/api/v1/purchase-orders/templates/:id", ({ params }) => {
      deleted.push(String(params.id));
      return new HttpResponse(null, { status: 204 });
    }),
    http.post("*/api/v1/purchase-orders/templates/seed-defaults", () => {
      seeded += 1;
      return HttpResponse.json([TEMPLATE], { status: 201 });
    }),
  );
}

/**
 * The order templates screen: the header's Add opens a blank editor, a
 * card's Edit opens that template, Delete asks first and removes only what
 * it named, and the empty state seeds the built-ins. A delete that skipped
 * its confirmation, or an Edit that opened a blank editor, fails here.
 */
describe("PurchaseOrdersTemplatesPage — editing, deleting and seeding", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    deleted = [];
    seeded = 0;
  });

  it("opens a blank editor from the header and closes it", async () => {
    serve([TEMPLATE]);
    const user = userEvent.setup();
    render(<PageHost />);
    await user.click(
      await within(
        screen.getByRole("banner", { name: "Page header" }),
      ).findByRole("button", { name: "Add Template" }),
    );
    const editor = screen.getByRole("dialog", { name: "Template editor" });
    expect(editor).toHaveTextContent("new template");
    await user.click(
      within(editor).getByRole("button", { name: "close editor" }),
    );
    expect(
      screen.queryByRole("dialog", { name: "Template editor" }),
    ).not.toBeInTheDocument();
  });

  it("opens the card's own template for editing", async () => {
    serve([TEMPLATE]);
    const user = userEvent.setup();
    render(<PageHost />);
    await user.click(
      await screen.findByRole("button", { name: "Edit Supplier copy" }),
    );
    expect(
      screen.getByRole("dialog", { name: "Template editor" }),
    ).toHaveTextContent("Supplier copy");
  });

  it("deletes a template only once the reader confirms", async () => {
    serve([TEMPLATE]);
    const user = userEvent.setup();
    render(<PageHost />);

    await user.click(
      await screen.findByRole("button", { name: "Delete Supplier copy" }),
    );
    let dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
    expect(deleted).toEqual([]);

    await user.click(
      screen.getByRole("button", { name: "Delete Supplier copy" }),
    );
    dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleted).toEqual(["tpl-1"]));
  });

  it("seeds the built-in layouts and opens a blank editor from the empty state", async () => {
    serve([]);
    const user = userEvent.setup();
    render(<PageHost />);
    await user.click(
      await screen.findByRole("button", { name: "Copy the built-in layouts" }),
    );
    await waitFor(() => expect(seeded).toBe(1));

    await user.click(
      screen.getByRole("button", { name: "Add your first template" }),
    );
    expect(
      screen.getByRole("dialog", { name: "Template editor" }),
    ).toHaveTextContent("new template");
  });

  it("retries a list that failed to load", async () => {
    let calls = 0;
    server.use(
      http.get("*/api/v1/purchase-orders/templates", () => {
        calls += 1;
        return calls === 1
          ? new HttpResponse(null, { status: 500 })
          : HttpResponse.json(onePage([TEMPLATE]));
      }),
    );
    const user = userEvent.setup();
    render(<PageHost />);
    await user.click(await screen.findByRole("button", { name: /try again/i }));
    expect(await screen.findByText("Supplier copy")).toBeInTheDocument();
  });
});
