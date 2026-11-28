import { describe, expect, it } from "vitest";

import { cleanup, render, screen } from "@/test/utils";
import { tFor, withLanguage } from "@/test/mocks/i18n";
import { ImportPreviewView, ImportResultView } from "./ImportPreviewSections";

/**
 * The import screen counted in one form for every number: "1 wierszy"
 * beside "4 wiersze", "1 błędów", "2 linii zaimportowanych", "1
 * niedopasowanych". Polish needs three forms after a numeral, and the
 * screen's own neighbour — the row counter — already had them.
 *
 * The gate (`check-plural-counts`) now reports the brace spelling of the
 * paste; this pins what a reader gets.
 */
const t = tFor("warehouse");

function renderPreview(totalRows: number, canCreateStubs = true) {
  render(
    <ImportPreviewView
      sourceLabel="plik.csv"
      totalRows={totalRows}
      headers={["Nazwa"]}
      mapping={{
        name: "A",
        brand: "",
        barcode: "",
        sku: "",
        quantity: "",
        uom_symbol: "",
        unit_price: "",
        tax_rate: "",
        batch_number: "",
        expiry_date: "",
      }}
      previewRows={[{ name: "Mleko" }]}
      onChangeMapping={() => {}}
      columnMappingForm={null}
      createStubsForUnmatched={false}
      canCreateStubs={canCreateStubs}
      onToggleCreateStubs={() => {}}
      t={t}
    />,
  );
}

describe("the import screen's preview", () => {
  it("shows the mapped expiry column as it will be stored", async () => {
    await withLanguage("pl", async () => {
      render(
        <ImportPreviewView
          sourceLabel="plik.csv"
          totalRows={1}
          headers={["Nazwa", "Ważne do"]}
          mapping={{
            name: "Nazwa",
            brand: "",
            barcode: "",
            sku: "",
            quantity: "",
            uom_symbol: "",
            unit_price: "",
            tax_rate: "",
            batch_number: "",
            expiry_date: "Ważne do",
          }}
          previewRows={[{ Nazwa: "Mleko", "Ważne do": "5 lis 2026" }]}
          previewRowsAsWritten={[{ Nazwa: "Mleko", "Ważne do": "05.11.2026" }]}
          onChangeMapping={() => {}}
          columnMappingForm={null}
          createStubsForUnmatched={false}
          canCreateStubs={true}
          onToggleCreateStubs={() => {}}
          t={t}
        />,
      );

      expect(screen.getByText("Data ważności")).toBeInTheDocument();
      expect(screen.getByText("5 lis 2026")).toBeInTheDocument();
      expect(screen.queryByText("05.11.2026")).toBeNull();
    });
  });
});

describe("the import screen's counters", () => {
  it("says one row, not one rows", async () => {
    await withLanguage("pl", async () => {
      renderPreview(1);

      expect(screen.getByText(/1 wiersz$/)).toBeInTheDocument();
      expect(screen.queryByText(/1 wierszy$/)).toBeNull();
    });
  });

  it("says four rows in the form four takes", async () => {
    await withLanguage("pl", async () => {
      renderPreview(4);

      expect(screen.getByText(/4 wiersze$/)).toBeInTheDocument();
    });
  });

  it("inflects the result's line, match and error counters too", async () => {
    await withLanguage("pl", async () => {
      render(
        <ImportResultView
          result={{
            imported: 1,
            matched: 2,
            unmatched: 1,
            stubs_created: 0,
            failed: 1,
            errors: [{ row: 3, error: "brak nazwy" }],
            no_stock: [],
            lines: [],
          }}
          t={t}
        />,
      );

      expect(screen.getByText("1 linia zaimportowana")).toBeInTheDocument();
      expect(
        screen.getByText(/2 dopasowane, 1 niedopasowany/),
      ).toBeInTheDocument();
      expect(screen.getByText("1 błąd")).toBeInTheDocument();
      expect(screen.queryByText("1 linii zaimportowanych")).toBeNull();
      expect(screen.queryByText("1 błędów")).toBeNull();
    });
  });

  it("names the lines that found no stock to take from", async () => {
    // A dispatch line needs a record on the source shelf; one the import
    // could not give one is named here, not discovered at confirmation.
    await withLanguage("pl", async () => {
      render(
        <ImportResultView
          result={{
            imported: 2,
            matched: 2,
            unmatched: 0,
            stubs_created: 0,
            failed: 0,
            errors: [],
            no_stock: [{ row: 2, name: "Kefir 1 l" }],
            lines: [],
          }}
          t={t}
        />,
      );

      const notice = screen.getByRole("status");
      expect(notice).toHaveTextContent(
        "1 linia nie znalazła stanu do pobrania",
      );
      expect(notice).toHaveTextContent("Wiersz 2: Kefir 1 l");
    });
  });

  it("offers the stub checkbox only to accounts that may found templates", async () => {
    await withLanguage("pl", async () => {
      renderPreview(1, true);
      expect(screen.getByRole("checkbox")).toBeInTheDocument();

      cleanup();
      renderPreview(1, false);
      expect(screen.queryByRole("checkbox")).toBeNull();
    });
  });

  it("counts every refusal, not the few listed", () => {
    render(
      <ImportResultView
        result={{
          imported: 0,
          matched: 0,
          unmatched: 0,
          stubs_created: 0,
          failed: 12,
          errors: Array.from({ length: 10 }, (_, i) => ({
            row: i + 1,
            error: "no name",
          })),
          no_stock: [],
          lines: [],
        }}
        t={tFor("warehouse")}
      />,
    );

    expect(screen.getByText(/^12 /)).toBeInTheDocument();
    expect(
      screen.getByText("Showing 5 of 12 refused rows."),
    ).toBeInTheDocument();
  });
});
