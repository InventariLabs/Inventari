import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@/test/utils";
import { downloadBlob } from "@/utils/helpers";
import { RefusedRows } from "./RefusedRows";

vi.mock("@/utils/helpers", () => ({ downloadBlob: vi.fn() }));

/** "Powód" in a UTF-8 file with its byte-order mark. */
const CONTENT = btoa(
  String.fromCharCode(...new TextEncoder().encode("\ufeffName;Powód\r\n")),
);

describe("RefusedRows", () => {
  beforeEach(() => vi.mocked(downloadBlob).mockClear());

  it("says how many rows were refused when the list shows fewer", () => {
    render(<RefusedRows failed={57} shown={10} />);

    expect(
      screen.getByText("Showing 10 of 57 refused rows."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("hands over the server's file byte for byte under its name", async () => {
    render(
      <RefusedRows
        failed={1}
        shown={1}
        file={{ filename: "stock-refused.csv", content_base64: CONTENT }}
      />,
    );
    expect(screen.queryByText(/Showing/)).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Download refused rows" }),
    );

    const [blob, name] = vi.mocked(downloadBlob).mock.calls[0];
    expect(name).toBe("stock-refused.csv");
    expect(blob.type).toBe("text/csv;charset=utf-8");
    const bytes = await new Promise<ArrayBuffer>((resolve) => {
      // jsdom's Blob is read through FileReader.
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as ArrayBuffer);
      reader.readAsArrayBuffer(blob);
    });

    expect(Array.from(new Uint8Array(bytes))).toEqual(
      Array.from(new TextEncoder().encode("\ufeffName;Powód\r\n")),
    );
  });
});
