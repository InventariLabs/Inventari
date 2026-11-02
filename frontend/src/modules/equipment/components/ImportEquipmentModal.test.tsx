import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import { downloadBlob } from "@/utils/helpers";

import ImportEquipmentModal from "./ImportEquipmentModal";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

vi.mock("@/contexts/ModulesContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ModulesContext")>()),
  useModules: () => ({
    enabledModules: ["equipment"],
    isModuleEnabled: () => true,
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

vi.mock("@/utils/helpers", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/utils/helpers")>()),
  downloadBlob: vi.fn(),
}));

const ANALYSIS = {
  headers: ["Asset", "Serial"],
  preview_rows: [{ Asset: "Dell Latitude", Serial: "SN-1" }],
  total_rows: 12,
  suggested_mapping: { name: "Asset", serial_number: "Serial" },
};

let executed: string;

beforeEach(() => {
  executed = "";
  server.use(
    http.get("/api/v1/locations", () =>
      HttpResponse.json(
        onePage([{ id: "loc-1", name: "Server Room", items_count: 0 }]),
      ),
    ),
    http.get("/api/v1/categories", () => HttpResponse.json(onePage([]))),
    http.post("/api/v1/equipment/import/analyze", () =>
      HttpResponse.json(ANALYSIS),
    ),
    http.post("/api/v1/equipment/import/execute", async ({ request }) => {
      executed = await request.text();
      return HttpResponse.json({
        imported: 11,
        failed: 1,
        skipped: 0,
        updated: 0,
        errors: [{ row: 7, error: "Serial number missing" }],
      });
    }),
  );
});

function renderModal(onClose = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ImportEquipmentModal onClose={onClose} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return onClose;
}

function chooseFile() {
  const input = document.querySelector(
    'input[type="file"]',
  ) as HTMLInputElement;
  const file = new File(["Asset,Serial\nDell Latitude,SN-1\n"], "assets.csv", {
    type: "text/csv",
  });
  fireEvent.change(input, { target: { files: [file] } });
}

/** The value of one multipart field in the request body, read as text. */
function partOf(body: string, name: string): string | undefined {
  const marker = `name="${name}"`;
  const start = body.indexOf(marker);
  if (start < 0) return undefined;
  const afterHeaders = body.indexOf("\r\n\r\n", start) + 4;
  return body.slice(afterHeaders, body.indexOf("\r\n", afterHeaders));
}

/**
 * The import is three steps — upload, mapping, result — and the reader's
 * choices on the second one are the request. The failures caught: the
 * server's suggested mapping not reaching the dropdowns, the duplicate
 * policy or the default location left out of the request, and a result
 * step that never shows how many rows failed.
 */
describe("ImportEquipmentModal — from file to result", () => {
  it("analyses the file, carries the reader's choices into the import, and reports the outcome", async () => {
    const user = userEvent.setup();
    const onClose = renderModal();

    expect(screen.getByRole("button", { name: /Analyze/ })).toBeDisabled();
    chooseFile();
    expect(screen.getByText("assets.csv")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Analyze/ }));

    expect(
      await screen.findByText("12 rows found — map columns below"),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("combobox", { name: "Duplicate serial numbers" }),
    );
    fireEvent.click(screen.getByRole("option", { name: "Update existing" }));
    fireEvent.click(screen.getByRole("combobox", { name: "Default location" }));
    fireEvent.click(await screen.findByText("Server Room"));

    await user.click(screen.getByRole("button", { name: "Import" }));

    expect(await screen.findByText(/Serial number missing/)).toBeVisible();
    expect(JSON.parse(partOf(executed, "mapping_json") ?? "null")).toEqual({
      name: "Asset",
      serial_number: "Serial",
      duplicate_mode: "update",
    });
    expect(partOf(executed, "default_location_id")).toBe("loc-1");
    expect(partOf(executed, "default_category_id")).toBeUndefined();

    // The dialog's corner X is called Close too; this is the result's own.
    await user.click(screen.getByText("Close", { selector: "button" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("will not import while no column is mapped to the name, and Back returns to the upload", async () => {
    server.use(
      http.post("/api/v1/equipment/import/analyze", () =>
        HttpResponse.json({ ...ANALYSIS, suggested_mapping: {} }),
      ),
    );
    const user = userEvent.setup();
    renderModal();

    chooseFile();
    await user.click(screen.getByRole("button", { name: /Analyze/ }));
    await screen.findByText("12 rows found — map columns below");
    expect(screen.getByRole("button", { name: "Import" })).toBeDisabled();

    fireEvent.click(screen.getByRole("combobox", { name: /^Name/ }));
    fireEvent.click(screen.getByRole("option", { name: "Asset" }));
    expect(screen.getByRole("button", { name: "Import" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByRole("button", { name: /Analyze/ })).toBeEnabled();
  });

  it("blames the file for a refusal and the server for a crash", async () => {
    server.use(
      http.post("/api/v1/equipment/import/analyze", () =>
        HttpResponse.json({}, { status: 422 }),
      ),
    );
    const user = userEvent.setup();
    renderModal();

    chooseFile();
    await user.click(screen.getByRole("button", { name: /Analyze/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not read the file. Check the format and try again.",
    );

    server.use(
      http.post("/api/v1/equipment/import/analyze", () =>
        HttpResponse.json({}, { status: 503 }),
      ),
    );
    await user.click(screen.getByRole("button", { name: /Analyze/ }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "The server could not analyse the file. Try again in a moment.",
      ),
    );

    // A new file is a new question: the old verdict goes.
    chooseFile();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("hands out a sample file whose header names the columns it reads", async () => {
    const user = userEvent.setup();
    renderModal();

    await user.click(
      screen.getByRole("button", { name: /Download a sample file/ }),
    );
    const [blob, filename] = vi.mocked(downloadBlob).mock.calls[0];
    expect(filename).toBe("equipment-import-template.csv");
    const text = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.readAsText(blob as Blob);
    });
    const [header, example] = text.split("\n");
    expect(header.split(",")).toEqual([
      "Name",
      "Manufacturer",
      "Serial number",
      "Asset tag",
      "Model",
      "Location",
      "Category",
      "Purchase price",
      "Purchase date",
      "Warranty until",
      "Notes",
      "Status",
    ]);
    expect(example.split(",")).toHaveLength(12);
  });
});
