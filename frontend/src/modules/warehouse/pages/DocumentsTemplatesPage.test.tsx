import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@/test/utils";
import { fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import i18next from "i18next";
import { http, HttpResponse } from "msw";
import { onePage } from "@/test/mocks/page";
import { toast } from "sonner";

import { server } from "@/test/mocks/server";
import { withLanguage } from "@/test/mocks/i18n";
import DocumentsTemplatesPage from "./DocumentsTemplatesPage";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const header = vi.hoisted(() => ({ setHeader: vi.fn() }));
vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({ setHeader: header.setHeader }),
}));

// The page gates its write actions on this; without a permission context it
// answers "no", and most of what these tests drive are write actions.
const rights = vi.hoisted(() => ({ write: true }));
vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => rights.write,
  useCanManage: () => rights.write,
}));

const builtIn = {
  name: "Standard Template",
  document_type: "STANDARD",
  body_html: "<html><body><h1>Delivery note</h1></body></html>",
};

/** What the server makes of the layout — the preview shows the page, not
 *  the source that produces it. */
const renderedBuiltIn =
  "<html><body><h1>Delivery note IN/2026/001</h1></body></html>";

function noTemplates() {
  server.use(
    http.get("*/api/v1/warehouse/templates", () =>
      HttpResponse.json(onePage([])),
    ),
    http.get("*/api/v1/warehouse/templates/built-in", () =>
      HttpResponse.json([builtIn]),
    ),
    http.post("*/api/v1/warehouse/templates/preview", () =>
      HttpResponse.json({ html: renderedBuiltIn }),
    ),
  );
}

describe("DocumentsTemplatesPage — built-in layouts that failed to load", () => {
  it("says so instead of dropping the preview entry point", async () => {
    server.use(
      http.get("*/api/v1/warehouse/templates", () =>
        HttpResponse.json(onePage([])),
      ),
      http.get(
        "*/api/v1/warehouse/templates/built-in",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    render(<DocumentsTemplatesPage />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });
});

describe("DocumentsTemplatesPage — nothing written yet", () => {
  it("shows the built-in layout instead of only offering to copy it", async () => {
    // The screen said built-in templates "will be used" and, beside that,
    // offered to load them — and showed neither, so the only way to find out
    // what a PDF looks like was to make one.
    noTemplates();
    render(<DocumentsTemplatesPage />);

    const preview = await screen.findByRole("button", {
      name: /see the built-in layout/i,
    });
    await userEvent.click(preview);

    const frame = await screen.findByTitle(/template preview/i);
    // The rendered page, not `{{ document.number }}` — a preview of the
    // source answers "what does this template say", not "what will it print".
    await waitFor(() =>
      expect(frame).toHaveAttribute("srcdoc", renderedBuiltIn),
    );
  });

  it("names the built-in layouts the print-layout picker also offers", async () => {
    // The empty screen said "a built-in layout" and "Add your first
    // template", while the print-layout selector already offered two by
    // name — the two places disagreed about what exists before anyone
    // writes a thing.
    noTemplates();
    render(<DocumentsTemplatesPage />);

    expect(await screen.findByText(/Standard layout/)).toBeInTheDocument();
    expect(screen.getByText(/PL PZ layout/)).toBeInTheDocument();
    expect(
      screen.getByText(/one of the two built-in layouts/i),
    ).toBeInTheDocument();
  });

  it("shows the printed page, never the template's own source", async () => {
    server.use(
      http.get("*/api/v1/warehouse/templates", () =>
        HttpResponse.json(onePage([])),
      ),
      http.get("*/api/v1/warehouse/templates/built-in", () =>
        HttpResponse.json([builtIn]),
      ),
      http.post("*/api/v1/warehouse/templates/preview", () =>
        HttpResponse.json({ html: "<p>IN/2026/001</p>" }),
      ),
    );
    render(<DocumentsTemplatesPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: /see the built-in layout/i }),
    );

    const frame = await screen.findByTitle(/template preview/i);
    await waitFor(() => {
      const srcdoc = frame.getAttribute("srcdoc") ?? "";
      expect(srcdoc).not.toContain("{{");
      expect(srcdoc).not.toContain("{%");
    });
  });

  it("names the copy action for what it does", async () => {
    noTemplates();
    render(<DocumentsTemplatesPage />);

    expect(
      await screen.findByRole("button", { name: /copy the built-in layouts/i }),
    ).toBeInTheDocument();
  });

  it("does not put a second filled create next to the header's", async () => {
    // The header owns the view's one primary call to action. The empty
    // state used to repeat the create as its own filled button, so the
    // empty screen carried two of them.
    noTemplates();
    render(<DocumentsTemplatesPage />);

    const create = await screen.findByRole("button", {
      name: /your first template/i,
    });
    expect(create).not.toHaveClass("bg-primary-700");
  });
});

describe("DocumentsTemplatesPage — the built-in layouts' names", () => {
  // The API names its layouts once, in English ("Standard Template"), and
  // the preview's picker printed that name as it came, so a Polish reader
  // chose between "Standard Template" and "Pick List". The names are the
  // ones the print-layout picker and the empty screen already use.
  const builtIns = [
    ["Standard Template", "STANDARD"],
    ["PL PZ Template", "PL_PZ"],
    ["Packing Slip", "PACKING_SLIP"],
    ["Pick List", "PICK_LIST"],
  ].map(([name, document_type]) => ({
    name,
    document_type,
    body_html: "<p>x</p>",
  }));

  it.each([
    ["en", ["Standard layout", "PL PZ layout", "Packing slip", "Pick list"]],
    [
      "pl",
      [
        "Układ standardowy",
        "Układ PZ (PL)",
        "List pakowy",
        "Lista kompletacji",
      ],
    ],
    ["de", ["Standardlayout", "PL-PZ-Layout", "Packliste", "Pickliste"]],
    [
      "fr",
      [
        "Mise en page standard",
        "Mise en page PL PZ",
        "Bordereau de colisage",
        "Bon de préparation",
      ],
    ],
    [
      "es",
      [
        "Diseño estándar",
        "Diseño PL PZ",
        "Lista de embalaje",
        "Lista de picking",
      ],
    ],
    [
      "pt",
      [
        "Layout padrão",
        "Layout PL PZ",
        "Romaneio de embalagem",
        "Lista de separação",
      ],
    ],
  ] as const)("read in the reader's language (%s)", async (language, names) => {
    noTemplates();
    server.use(
      http.get("*/api/v1/warehouse/templates/built-in", () =>
        HttpResponse.json(builtIns),
      ),
    );

    await withLanguage(language, async () => {
      render(<DocumentsTemplatesPage />);
      await userEvent.click(
        await screen.findByRole("button", {
          name: i18next.t("warehouse:templates.builtInPreviewAction"),
        }),
      );

      const picker = await screen.findByRole("combobox", {
        name: i18next.t("warehouse:templates.builtInPreviewTitle"),
      });
      expect(
        within(picker)
          .getAllByRole("option")
          .map((option) => option.textContent),
      ).toEqual(names);
    });
  });
});

describe("DocumentsTemplatesPage — a copy of an older built-in", () => {
  const copy = {
    id: "t1",
    module: "warehouse",
    name: "Standard Template",
    document_type: "STANDARD",
    body_html: "<p>ours</p>",
    version: 1,
    is_default: true,
    created_by: null,
    created_at: "2026-01-02T00:00:00Z",
    updated_at: null,
    source_builtin: "Standard Template",
  };

  it("says nothing while the copy still matches the built-in", async () => {
    server.use(
      http.get("*/api/v1/warehouse/templates", () =>
        HttpResponse.json(onePage([{ ...copy, source_outdated: false }])),
      ),
      http.get("*/api/v1/warehouse/templates/built-in", () =>
        HttpResponse.json([builtIn]),
      ),
    );
    render(<DocumentsTemplatesPage />);

    await screen.findByText("Standard Template");
    expect(
      screen.queryByTestId("template-outdated-note"),
    ).not.toBeInTheDocument();
  });

  it("says the built-in has moved on, and offers a copy alongside", async () => {
    const refreshed = vi.fn();
    server.use(
      http.get("*/api/v1/warehouse/templates", () =>
        HttpResponse.json(onePage([{ ...copy, source_outdated: true }])),
      ),
      http.get("*/api/v1/warehouse/templates/built-in", () =>
        HttpResponse.json([builtIn]),
      ),
      http.post("*/api/v1/warehouse/templates/t1/refresh-copy", () => {
        refreshed();
        return HttpResponse.json(
          {
            ...copy,
            id: "t2",
            name: "Standard Template (2)",
            is_default: false,
          },
          { status: 201 },
        );
      }),
    );
    render(<DocumentsTemplatesPage />);

    expect(
      await screen.findByTestId("template-outdated-note"),
    ).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", {
        name: /copy the current built-in alongside/i,
      }),
    );
    await waitFor(() => expect(refreshed).toHaveBeenCalled());
  });
});

describe("DocumentsTemplatesPage — an account that may only read", () => {
  afterEach(() => {
    rights.write = true;
  });

  it("offers no way to write a template, and says why", async () => {
    // The editor used to open in full for an account holding `warehouse:read`
    // alone — Add Template, Edit and Delete on all eight templates — and the
    // refusal arrived after the HTML was written. This screen was also the one
    // module page with no notice at all, so with the buttons gone it would
    // have read as broken rather than as a boundary.
    rights.write = false;
    server.use(
      http.get("*/api/v1/warehouse/templates", () =>
        HttpResponse.json(
          onePage([
            {
              id: "t1",
              module: "warehouse",
              name: "Standard Template",
              document_type: "STANDARD",
              body_html: "<p>ours</p>",
              version: 1,
              is_default: true,
              created_by: null,
              created_at: "2026-01-02T00:00:00Z",
              updated_at: null,
              source_builtin: "Standard Template",
              source_outdated: false,
            },
          ]),
        ),
      ),
      http.get("*/api/v1/warehouse/templates/built-in", () =>
        HttpResponse.json([builtIn]),
      ),
    );
    render(<DocumentsTemplatesPage />);

    await screen.findByText("Standard Template");
    expect(
      screen.queryByRole("button", { name: /edit/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /delete/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("note")).toBeInTheDocument();
  });

  it("does not invite an empty catalogue to be filled", async () => {
    rights.write = false;
    noTemplates();
    render(<DocumentsTemplatesPage />);

    await screen.findByRole("note");
    expect(
      screen.queryByRole("button", { name: /load built-in templates/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /create your first template/i }),
    ).not.toBeInTheDocument();
  });
});

describe("DocumentsTemplatesPage — confirming a deletion", () => {
  it("names the template it is about to remove", async () => {
    // The window whose only job is to say WHAT disappears read
    // `Delete template "{{name}}"?`: the call passed the name as t()'s second
    // argument, which i18next reads as a default value, so nothing was ever
    // handed over to fill the placeholder.
    server.use(
      http.get("*/api/v1/warehouse/templates", () =>
        HttpResponse.json(
          onePage([
            {
              id: "t1",
              module: "warehouse",
              name: "Delivery Note EU",
              document_type: "STANDARD",
              body_html: "<p>ours</p>",
              version: 1,
              is_default: false,
              created_by: null,
              created_at: "2026-01-02T00:00:00Z",
              updated_at: null,
              source_builtin: null,
              source_outdated: false,
            },
          ]),
        ),
      ),
      http.get("*/api/v1/warehouse/templates/built-in", () =>
        HttpResponse.json([builtIn]),
      ),
    );
    render(<DocumentsTemplatesPage />);

    await screen.findByText("Delivery Note EU");
    await userEvent.click(screen.getByRole("button", { name: /delete/i }));

    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Delivery Note EU");
    expect(dialog).not.toHaveTextContent("{{name}}");
  });
});

describe("DocumentsTemplatesPage — the dialog and the badge speak the documents' language", () => {
  /** The template's type used to be a layout family ("Standard", "PL PZ")
   *  that the print endpoint never read; now it is one of the seven
   *  document types, under the same labels the documents list prints. */
  const scrapTemplate = {
    id: "tpl-scrap",
    name: "Scrap layout",
    document_type: "SCRAP",
    body_html: "<html><body><h1>Scrap</h1></body></html>",
    is_default: false,
    module: "warehouse",
  };

  function withTemplates() {
    server.use(
      http.get("*/api/v1/warehouse/templates", () =>
        HttpResponse.json(onePage([scrapTemplate])),
      ),
      http.get("*/api/v1/warehouse/templates/built-in", () =>
        HttpResponse.json([builtIn]),
      ),
    );
  }

  it("offers the seven document types under the documents list's labels", async () => {
    withTemplates();
    render(<DocumentsTemplatesPage />);

    // The write actions live in the page header, which the mock captures —
    // render them beside the page to reach the dialog the operator uses.
    const actions = header.setHeader.mock.lastCall?.[0]?.actions;
    if (actions) render(<div>{actions}</div>);

    await userEvent.click(
      await screen.findByRole("button", { name: /add template/i }),
    );

    const typeSelect = await screen.findByRole("combobox", { name: /type/i });
    const labels = [
      ...screen.getAllByRole("option"),
      ...[...typeSelect.querySelectorAll("option")].map((o) => o.textContent),
    ];
    for (const expected of [
      "Receipt",
      "Delivery",
      "Transfer",
      "Internal receipt",
      "Internal issue",
      "Scrap",
    ]) {
      expect(labels).toContain(expected);
    }
    // Layout families are not document types — they never named a document.
    expect(labels).not.toContain("Standard");
  });

  it("describes each symbol in the reader's language, nested ones included", async () => {
    // The API describes symbols in English only; this editor passed the
    // dialog no catalogue, so a Polish reader got the API's sentence.
    withTemplates();
    server.use(
      http.get("*/api/v1/warehouse/templates/placeholders", () =>
        HttpResponse.json([
          {
            key: "{{code128_height_mm}}",
            description: "Height the barcode must print at, in millimetres",
          },
          {
            key: "{{document.number}}",
            description: "The document number, as the register knows it",
          },
        ]),
      ),
    );

    await withLanguage("pl", async () => {
      render(<DocumentsTemplatesPage />);
      const actions = header.setHeader.mock.lastCall?.[0]?.actions;
      if (actions) render(<div>{actions}</div>);

      await userEvent.click(
        await screen.findByRole("button", { name: /dodaj szablon/i }),
      );

      for (const [key, polish] of [
        [
          "{{code128_height_mm}}",
          "Wysokość, z jaką musi się wydrukować kod kreskowy, w milimetrach",
        ],
        ["{{document.number}}", "Numer dokumentu, taki jak w rejestrze"],
      ]) {
        const symbol = (await screen.findByText(key)).closest("button");
        expect(symbol).toHaveAttribute("title", polish);
        expect(symbol).toHaveTextContent(polish);
      }
    });
  });

  it("the list badge reads the same label the dialog offers", async () => {
    withTemplates();
    render(<DocumentsTemplatesPage />);

    // The card badge for document_type "SCRAP" prints the documents list's
    // own word, not the raw code and not a layout family.
    expect(await screen.findByText("Scrap")).toBeInTheDocument();
  });
});

describe("DocumentsTemplatesPage — editing a legacy-typed copy", () => {
  /** The built-in copies were born with layout-family types the seven
   *  document types don't include. A select whose options lack the value
   *  the template carries renders its first option instead — the editor
   *  showed "Receipt" for a PL PZ copy, and saving through that shown
   *  value silently rewrote the template's type. The editor has to offer
   *  the type the template actually has. */
  const legacy = {
    id: "tpl-plpz",
    name: "PL PZ Template",
    document_type: "PL_PZ",
    body_html: "<html><body><h1>PL PZ</h1></body></html>",
    is_default: false,
    module: "warehouse",
  };

  function withLegacy() {
    server.use(
      http.get("*/api/v1/warehouse/templates", () =>
        HttpResponse.json(onePage([legacy])),
      ),
      http.get("*/api/v1/warehouse/templates/built-in", () =>
        HttpResponse.json([]),
      ),
    );
  }

  it("offers the template's own type, not the first option", async () => {
    withLegacy();
    render(<DocumentsTemplatesPage />);

    await userEvent.click(await screen.findByRole("button", { name: /edit/i }));

    const typeSelect = (await screen.findByRole("combobox", {
      name: /type/i,
    })) as HTMLSelectElement;
    const values = [...typeSelect.querySelectorAll("option")].map(
      (o) => o.value,
    );
    expect(values).toContain("PL_PZ");
    expect(typeSelect.value).toBe("PL_PZ");
  });
});

describe("DocumentsTemplatesPage — the packing slip", () => {
  /** The packing slip is a built-in like the document layouts, typed
   *  PACKING_SLIP: its copy is named in words and the editor offers the
   *  type once, so an organization's own slip can be written and kept. */
  const slip = {
    id: "tpl-slip",
    name: "Packing Slip",
    document_type: "PACKING_SLIP",
    body_html: "<html><body>{{ packages }}</body></html>",
    is_default: true,
    module: "warehouse",
  };

  it("names the type in words and offers it once in the editor", async () => {
    server.use(
      http.get("*/api/v1/warehouse/templates", () =>
        HttpResponse.json(onePage([slip])),
      ),
      http.get("*/api/v1/warehouse/templates/built-in", () =>
        HttpResponse.json([]),
      ),
    );
    render(<DocumentsTemplatesPage />);

    expect(await screen.findByText("Packing slip")).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: /edit/i }));

    const typeSelect = (await screen.findByRole("combobox", {
      name: /type/i,
    })) as HTMLSelectElement;
    const values = [...typeSelect.querySelectorAll("option")].map(
      (o) => o.value,
    );
    expect(values.filter((v) => v === "PACKING_SLIP")).toHaveLength(1);
    expect(typeSelect.value).toBe("PACKING_SLIP");
  });
});

describe("DocumentsTemplatesPage — a template leaves, a template arrives", () => {
  const mine = {
    id: "t1",
    module: "warehouse",
    name: "German receipt",
    document_type: "IN",
    body_html: "<p>{{ document.number }}</p>",
    version: 1,
    is_default: false,
    created_by: null,
    created_at: "2026-01-02T00:00:00Z",
    updated_at: null,
    source_builtin: null,
  };

  const oneTemplate = () =>
    server.use(
      http.get("*/api/v1/warehouse/templates", () =>
        HttpResponse.json(onePage([mine])),
      ),
      http.get("*/api/v1/warehouse/templates/built-in", () =>
        HttpResponse.json([]),
      ),
    );

  it("downloads one file under the template's own name", async () => {
    oneTemplate();
    let exported = 0;
    server.use(
      http.get("*/api/v1/warehouse/templates/t1/export", () => {
        exported += 1;
        return HttpResponse.json({
          kind: "inventari.document-template",
          version: 1,
          name: "German receipt",
          document_type: "IN",
          is_default: false,
          body_html: mine.body_html,
        });
      }),
    );
    render(<DocumentsTemplatesPage />);

    await userEvent.click(
      await screen.findByRole("button", {
        name: /export template german receipt/i,
      }),
    );

    await waitFor(() => expect(exported).toBe(1));
  });

  it("imports a file and announces the template it created", async () => {
    let imports = 0;
    let lists = 0;
    server.use(
      http.get("*/api/v1/warehouse/templates", () => {
        lists += 1;
        return HttpResponse.json(onePage([]));
      }),
      http.get("*/api/v1/warehouse/templates/built-in", () =>
        HttpResponse.json([]),
      ),
      http.post("*/api/v1/warehouse/templates/import", () => {
        imports += 1;
        return HttpResponse.json({ ...mine, id: "t2" }, { status: 201 });
      }),
    );
    const { container } = render(<DocumentsTemplatesPage />);
    await screen.findByText(/add your first template/i);
    const listsBefore = lists;

    // The picker is hidden and opened by the header button — which the
    // shell renders, not this page — so the change is dispatched the way
    // the browser's own file chooser would.
    fireEvent.change(
      container.querySelector("input[type=file]") as HTMLInputElement,
      {
        target: {
          files: [
            new File(["{}"], "template.json", { type: "application/json" }),
          ],
        },
      },
    );

    await waitFor(() => expect(imports).toBe(1));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        expect.stringContaining("German receipt"),
      ),
    );
    // The list came back, with the imported template on it.
    await waitFor(() => expect(lists).toBeGreaterThan(listsBefore));
  });

  it("passes the server's refusal on, with the placeholder it names", async () => {
    server.use(
      http.get("*/api/v1/warehouse/templates", () =>
        HttpResponse.json(onePage([])),
      ),
      http.get("*/api/v1/warehouse/templates/built-in", () =>
        HttpResponse.json([]),
      ),
      http.post("*/api/v1/warehouse/templates/import", () =>
        HttpResponse.json(
          {
            detail: {
              code: "VALIDATION_ERROR",
              message:
                "The template references fields that do not exist: nonexistent_field.",
            },
          },
          { status: 400 },
        ),
      ),
    );
    const { container } = render(<DocumentsTemplatesPage />);
    await screen.findByText(/add your first template/i);

    fireEvent.change(
      container.querySelector("input[type=file]") as HTMLInputElement,
      {
        target: {
          files: [
            new File(["{}"], "template.json", { type: "application/json" }),
          ],
        },
      },
    );

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringContaining("nonexistent_field"),
      ),
    );
  });
});
