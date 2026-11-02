import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { csvCell, toCsv, downloadCsv } from "../csv";

describe("csvCell", () => {
  it("leaves an ordinary value alone", () => {
    expect(csvCell("Kawa mielona")).toBe("Kawa mielona");
    expect(csvCell(12.5)).toBe("12.5");
  });

  it("writes nothing for a missing value", () => {
    expect(csvCell(null)).toBe("");
    expect(csvCell(undefined)).toBe("");
  });

  it("quotes a value with a comma, so the columns after it do not shift", () => {
    expect(csvCell("Warszawa, Mokotów")).toBe('"Warszawa, Mokotów"');
  });

  it("doubles a quote inside a quoted field", () => {
    expect(csvCell('Patelnia 12" nieprzywierająca')).toBe(
      '"Patelnia 12"" nieprzywierająca"',
    );
  });

  it("quotes a value with a newline", () => {
    expect(csvCell("dwie\nlinie")).toBe('"dwie\nlinie"');
  });
});

describe("toCsv", () => {
  it("joins rows with the header the caller put first", () => {
    expect(
      toCsv([
        ["name", "qty"],
        ["Kawa", 2],
        ["Herbata, zielona", 1],
      ]),
    ).toBe('name,qty\nKawa,2\n"Herbata, zielona",1');
  });
});

describe("downloadCsv", () => {
  const createObjectURL = vi.fn(() => "blob:test");
  const revokeObjectURL = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL,
      revokeObjectURL,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("puts the byte-order mark in front so a spreadsheet reads UTF-8", () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click");
    click.mockImplementation(() => {});
    // jsdom's Blob cannot be read back, so record what was handed to it.
    const parts: BlobPart[][] = [];
    const RealBlob = globalThis.Blob;
    class RecordingBlob extends RealBlob {
      constructor(blobParts: BlobPart[] = [], options?: BlobPropertyBag) {
        super(blobParts, options);
        parts.push(blobParts);
      }
    }
    vi.stubGlobal("Blob", RecordingBlob);

    downloadCsv("nazwa\nZupa ogórkowa", "raport.csv");

    expect(parts).toHaveLength(1);
    expect(parts[0]).toEqual(["﻿nazwa\nZupa ogórkowa"]);
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    click.mockRestore();
  });
});
