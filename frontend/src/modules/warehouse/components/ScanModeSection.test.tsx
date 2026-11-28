import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { tFor } from "@/test/mocks/i18n";
import { ScanModeSection } from "./ScanModeSection";

vi.mock("@/components/ui/ScanCameraPanel", () => ({
  ScanCameraPanel: () => null,
}));

const section = (scanMode: boolean, cameraOpen: boolean) => (
  <ScanModeSection
    scanMode={scanMode}
    cameraOpen={cameraOpen}
    scanValue=""
    scanFeedback={null}
    scanFeedbackTone="neutral"
    lineStatusCounts={{ PENDING: 1, DONE: 0, PARTIAL: 0, EXCEPTION: 0 }}
    scanTargetLine={null}
    nextIncompleteLine={null}
    scannerError={null}
    isCameraActive={false}
    isTorchOn={false}
    onToggleScanMode={vi.fn()}
    onCameraToggle={vi.fn()}
    onScanValueChange={vi.fn()}
    onApplyScan={vi.fn()}
    onToggleTorch={vi.fn()}
    onRetryCamera={vi.fn()}
    t={tFor("warehouse")}
  />
);

/** Both switches say whether what they open is open. */
describe("ScanModeSection — scan mode and camera", () => {
  it("says scan mode is closed", () => {
    render(section(false, false));
    expect(screen.getByRole("button")).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it.each([false, true])("says whether the camera is open (%s)", (open) => {
    render(section(true, open));
    const [mode, , camera] = screen.getAllByRole("button");
    expect(mode).toHaveAttribute("aria-expanded", "true");
    expect(camera).toHaveAttribute("aria-expanded", String(open));
  });
});
