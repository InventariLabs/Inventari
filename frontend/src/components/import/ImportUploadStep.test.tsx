import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { withLanguage } from "@/test/mocks/i18n";
import { ImportUploadStep } from "./ImportUploadStep";

const grocy = { label: "Import from Grocy", hint: "Use your Grocy CSV export" };

describe("ImportUploadStep", () => {
  it("renders the generic tile and the named source when given one", () => {
    render(<ImportUploadStep onFileSelect={vi.fn()} secondaryUpload={grocy} />);

    expect(screen.getByText("Generic XLSX/CSV")).toBeInTheDocument();
    expect(screen.getByText("Import from Grocy")).toBeInTheDocument();
  });

  it("renders only the generic tile without a named source", () => {
    render(<ImportUploadStep onFileSelect={vi.fn()} />);

    expect(screen.getByText("Generic XLSX/CSV")).toBeInTheDocument();
    expect(screen.queryByText("Import from Grocy")).not.toBeInTheDocument();
  });

  it("displays info box with important note", () => {
    render(<ImportUploadStep onFileSelect={vi.fn()} />);

    expect(screen.getByText("Important note")).toBeInTheDocument();
    expect(
      screen.getByText(/Make sure the file has a header row/),
    ).toBeInTheDocument();
  });

  /** The step used to render its copy as literals, which an English test
   *  cannot tell apart from a translated string. */
  it("speaks the interface language, not the language it was written in", async () => {
    await withLanguage("pl", async () => {
      const { unmount } = render(<ImportUploadStep onFileSelect={vi.fn()} />);

      expect(screen.getByText("Ważna uwaga")).toBeInTheDocument();
      expect(screen.queryByText("Important note")).not.toBeInTheDocument();
      unmount();
    });
  });

  it("has hidden file input", () => {
    render(<ImportUploadStep onFileSelect={vi.fn()} />);

    const fileInput = document.getElementById(
      "import-file",
    ) as HTMLInputElement;
    expect(fileInput).toBeInTheDocument();
    expect(fileInput).toHaveAttribute("type", "file");
    expect(fileInput).toHaveAttribute("accept", ".xlsx,.xls,.csv");
  });

  it.each(["Generic XLSX/CSV", "Import from Grocy"])(
    "opens the file chooser when the %s tile is pressed",
    async (tile) => {
      render(
        <ImportUploadStep onFileSelect={vi.fn()} secondaryUpload={grocy} />,
      );
      const fileInput = document.getElementById("import-file") as HTMLElement;
      const opened = vi.fn((e: Event) => e.preventDefault());
      fileInput.addEventListener("click", opened);

      await userEvent.click(screen.getByText(tile));

      expect(opened).toHaveBeenCalledTimes(1);
    },
  );

  it("hands the chosen file to the wizard", async () => {
    const onFileSelect = vi.fn();
    render(<ImportUploadStep onFileSelect={onFileSelect} />);
    const file = new File(["a,b"], "stock.csv", { type: "text/csv" });

    await userEvent.upload(
      document.getElementById("import-file") as HTMLInputElement,
      file,
    );

    expect(onFileSelect).toHaveBeenCalledExactlyOnceWith(file);
  });
});
