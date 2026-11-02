import { render, screen, fireEvent } from "@/test/utils";
import { describe, it, expect, vi } from "vitest";
import { scanWithHardwareScanner } from "@/test/scanner";
import ScanCameraView from "./ScanCameraView";

/**
 * When the camera fails on a phone — permission denied, no camera,
 * device busy — the error overlay covered the whole view, and the manual code
 * entry only existed in the branch underneath it. That left no way to scan.
 */
const baseProps = {
  isCameraActive: false,
  scannerError: null as string | null,
  isTorchOn: false,
  storageContext: null,
  onBack: vi.fn(),
  onStartCamera: vi.fn(),
  onRestartCamera: vi.fn(),
  onToggleTorch: vi.fn(),
  onClearStorageContext: vi.fn(),
};

describe("ScanCameraView — typing a code by hand", () => {
  it("is offered when the camera is not running", () => {
    render(<ScanCameraView {...baseProps} onManualCode={vi.fn()} />);

    expect(screen.getByTestId("manual-barcode-input")).toBeInTheDocument();
  });

  it("is still offered after the camera fails", () => {
    render(
      <ScanCameraView
        {...baseProps}
        scannerError="Permission denied"
        onManualCode={vi.fn()}
      />,
    );

    expect(screen.getByTestId("manual-barcode-input")).toBeInTheDocument();
  });

  it("submits the typed code from the error state", () => {
    const onManualCode = vi.fn();
    render(
      <ScanCameraView
        {...baseProps}
        scannerError="Permission denied"
        onManualCode={onManualCode}
      />,
    );

    const input = screen.getByTestId("manual-barcode-input");
    fireEvent.change(input, { target: { value: "5901234123457" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onManualCode).toHaveBeenCalledWith("5901234123457");
  });

  it("hands over a code a hardware scanner reads, with the camera running", () => {
    const onManualCode = vi.fn();
    render(
      <ScanCameraView
        {...baseProps}
        isCameraActive
        onManualCode={onManualCode}
      />,
    );

    scanWithHardwareScanner("5901234123457", document.body);

    expect(onManualCode).toHaveBeenCalledTimes(1);
    expect(onManualCode).toHaveBeenCalledWith("5901234123457");
  });

  it("says a hardware scanner can be used where the code field is offered", () => {
    render(<ScanCameraView {...baseProps} onManualCode={vi.fn()} />);

    expect(
      screen.getByText("A barcode scanner can be used on this screen"),
    ).toBeInTheDocument();
  });

  it("puts the focus in the code field on a desktop, where a USB scanner types", () => {
    vi.mocked(window.matchMedia).mockImplementation(
      (query: string) =>
        ({
          matches: query === "(min-width: 768px)",
          media: query,
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
        }) as unknown as MediaQueryList,
    );
    try {
      render(<ScanCameraView {...baseProps} onManualCode={vi.fn()} />);

      expect(screen.getByTestId("manual-barcode-input")).toHaveFocus();
    } finally {
      vi.mocked(window.matchMedia).mockImplementation(
        (query: string) =>
          ({
            matches: false,
            media: query,
            addEventListener: vi.fn(),
            removeEventListener: vi.fn(),
          }) as unknown as MediaQueryList,
      );
    }
  });

  it("leaves the focus alone on a phone, where it would cover the camera with a keyboard", () => {
    render(<ScanCameraView {...baseProps} onManualCode={vi.fn()} />);

    expect(screen.getByTestId("manual-barcode-input")).not.toHaveFocus();
  });

  it("stays out of the way when the caller cannot take a code", () => {
    render(<ScanCameraView {...baseProps} scannerError="Permission denied" />);

    expect(screen.queryByTestId("manual-barcode-input")).toBeNull();
  });

  // The other scanning screen. Its refusal overlay replaces the viewfinder and
  // its "aim at the code" line outright, so nothing here claims the camera is
  // looking while it has refused — the failure reaches the reader as the
  // device state, not as the wish to scan.
  it("takes the viewfinder down, not just the video, when the camera refuses", () => {
    render(
      <ScanCameraView
        {...baseProps}
        isCameraActive
        scannerError="This camera does not meet the scanner's requirements."
        onManualCode={vi.fn()}
      />,
    );

    expect(screen.queryByTestId("scan-instructions")).not.toBeInTheDocument();
    expect(
      screen.getByText("This camera does not meet the scanner's requirements."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("You can also type the code by hand below."),
    ).toBeInTheDocument();
  });

  // html5-qrcode derives the decode region from the video's client size and
  // assumes the picture is scaled, not cropped. Forcing the video to cover the
  // screen made the decoder read a stretched slice whenever the stream's shape
  // differed from the screen's.
  it("does not force the video to fill and crop to the screen", () => {
    const { container } = render(
      <ScanCameraView {...baseProps} isCameraActive />,
    );

    const root = container.firstElementChild as HTMLElement;
    expect(root.className).not.toMatch(/\[&_video\]/);
  });
});

describe("ScanCameraView — a refused code", () => {
  it("stays readable beside the manual field, with the search and a way to close it", () => {
    const onSearch = vi.fn();
    const onDismiss = vi.fn();
    render(
      <ScanCameraView
        {...baseProps}
        onManualCode={vi.fn()}
        lookupFailure={{ code: "NOPE-1", message: "Nothing matches", onSearch }}
        onDismissLookupFailure={onDismiss}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("NOPE-1");
    expect(screen.getByRole("alert")).toHaveTextContent("Nothing matches");
    fireEvent.click(
      screen.getByRole("button", { name: "Search for this code" }),
    );
    expect(onSearch).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("is absent when nothing was refused", () => {
    render(<ScanCameraView {...baseProps} onManualCode={vi.fn()} />);

    expect(screen.queryByRole("alert")).toBeNull();
  });
});
