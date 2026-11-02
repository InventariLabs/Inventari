import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import { StepCard } from "./StepCard";

function renderStep(isActive: boolean) {
  return render(
    <StepCard
      step={{ type: "step", stepNumber: 1, body: "Stir" }}
      isActive={isActive}
      timerForStep={null}
      timerSeconds={null}
      timerRunning={false}
      t={((k: string) => k) as never}
      onStartTimer={vi.fn()}
      onToggleTimer={vi.fn()}
      onResetTimer={vi.fn()}
    />,
  );
}

describe("StepCard", () => {
  it("numbers the active step on a fill white text clears 4.5:1 on", () => {
    renderStep(true);

    const badge = screen.getByText("1").parentElement;
    expect(badge).toHaveClass("bg-primary-800", "text-white");
    expect(badge).not.toHaveClass("bg-primary-500");
  });
});
