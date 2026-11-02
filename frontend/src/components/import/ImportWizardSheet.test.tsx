import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, type AxiosResponse } from "axios";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { toast } from "sonner";
import { ImportWizardSheet } from "./ImportWizardSheet";

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

function refusal(status: number, detail: unknown) {
  return new AxiosError("failed", "ERR_BAD_REQUEST", undefined, undefined, {
    status,
    data: { detail },
  } as AxiosResponse);
}

function renderWizard(analyze: () => Promise<never>) {
  render(
    <ImportWizardSheet
      onClose={vi.fn()}
      title="Import"
      formats="XLSX / CSV"
      fields={[]}
      requiredField="name"
      analyze={analyze}
      suggest={() => ({})}
      run={vi.fn()}
      texts={{
        analyzeFailed: "Failed to analyze file",
        importFailed: "Import failed",
        wait: "Wait",
        added: () => "Added",
        closeAndView: "Close",
      }}
    />,
  );
}

async function upload() {
  const input = document.querySelector('input[type="file"]') as HTMLElement;
  await userEvent.upload(
    input,
    new File(["a,b"], "sample.csv", { type: "text/csv" }),
  );
}

describe("ImportWizardSheet analyze failure", () => {
  beforeEach(() => vi.mocked(toast.error).mockClear());

  it("shows the sentence the server wrote", async () => {
    renderWizard(() => Promise.reject(refusal(413, "File is too large")));
    await upload();

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("File is too large"),
    );
  });

  it("falls back to the generic text when the error carries no sentence", async () => {
    renderWizard(() => Promise.reject(new Error("boom")));
    await upload();

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Failed to analyze file"),
    );
    expect(screen.queryByText("boom")).not.toBeInTheDocument();
  });
});

describe("ImportWizardSheet mapping step", () => {
  it("goes back to choosing a file when the reader presses Back, without closing the sheet", async () => {
    const onClose = vi.fn();
    render(
      <ImportWizardSheet
        onClose={onClose}
        title="Import"
        formats="XLSX / CSV"
        fields={[{ key: "name", label: "Product name", required: true }]}
        requiredField="name"
        analyze={() =>
          Promise.resolve({
            headers: ["name"],
            preview_rows: [],
            total_rows: 0,
            filled_counts: {},
          })
        }
        suggest={() => ({ name: "name" })}
        run={vi.fn()}
        texts={{
          analyzeFailed: "Failed to analyze file",
          importFailed: "Import failed",
          wait: "Wait",
          added: () => "Added",
          closeAndView: "Close",
        }}
      />,
    );
    await upload();
    expect(await screen.findByText("Product name")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Back" }));

    expect(screen.getByText("Generic XLSX/CSV")).toBeInTheDocument();
    expect(screen.queryByText("Product name")).not.toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });
});
