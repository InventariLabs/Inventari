import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { onePage } from "@/test/mocks/page";

import { server } from "@/test/mocks/server";
import { withLanguage } from "@/test/mocks/i18n";
import PurchaseOrdersTemplatesPage from "./PurchaseOrdersTemplatesPage";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const header = vi.hoisted(() => ({ setHeader: vi.fn() }));
vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({ setHeader: header.setHeader }),
}));

vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => true,
  useCanManage: () => true,
}));

const placeholders = [
  { key: "{{po_number}}", description: "PO number (auto-generated)" },
];

/** The screen with nothing written yet, so its own door to the editor shows. */
function noTemplates() {
  server.use(
    http.get("*/api/v1/purchase-orders/templates", () =>
      HttpResponse.json(onePage([])),
    ),
    http.get("*/api/v1/purchase-orders/templates/placeholders", () =>
      HttpResponse.json(placeholders),
    ),
  );
}

describe("PurchaseOrdersTemplatesPage — the symbol list", () => {
  it("names a symbol the same way in the tooltip and in the line under it", async () => {
    // The tooltip was the API's English while the line six pixels below it
    // went through the catalogue — one button, two languages. The reader
    // hovering a symbol got a different answer than the reader looking at it.
    noTemplates();

    await withLanguage("pl", async () => {
      render(<PurchaseOrdersTemplatesPage />);

      await userEvent.click(
        await screen.findByRole("button", { name: "Dodaj pierwszy szablon" }),
      );

      const code = await screen.findByText("{{po_number}}");
      const button = code.closest("button");
      const described = "Numer ZP (generowany automatycznie)";

      expect(button).toHaveAttribute("title", described);
      expect(button).toHaveTextContent(described);
      expect(button).not.toHaveAttribute("title", "PO number (auto-generated)");
    });
  });
});
