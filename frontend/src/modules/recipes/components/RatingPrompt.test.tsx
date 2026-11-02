import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import i18n from "@/i18n/config";
import { RatingPrompt } from "./RatingPrompt";

const t = i18n.t.bind(i18n);

const setup = (over: Partial<Parameters<typeof RatingPrompt>[0]> = {}) => {
  const onRate = vi.fn();
  const onSkip = vi.fn();
  render(
    <RatingPrompt
      open
      recipeName="Pancakes"
      isSaving={false}
      onRate={onRate}
      onSkip={onSkip}
      t={t}
      {...over}
    />,
  );
  return { onRate, onSkip };
};

const star = (n: number) =>
  screen.getByRole("button", { name: `Rate ${n} star(s)` });

/**
 * The rating sheet asked right after cooking: nothing is sent until a star is
 * chosen, and the star chosen is the star sent.
 */
describe("RatingPrompt", () => {
  it("names the recipe being rated", () => {
    setup();
    expect(screen.getByText("Pancakes")).toBeInTheDocument();
  });

  it("will not submit before a star is chosen", () => {
    const { onRate } = setup();
    const submit = screen.getByRole("button", { name: "Rate" });
    expect(submit).toBeDisabled();
    fireEvent.click(submit);
    expect(onRate).not.toHaveBeenCalled();
  });

  it("sends the chosen star count", () => {
    const { onRate } = setup();
    fireEvent.click(star(4));
    fireEvent.click(screen.getByRole("button", { name: "Rate" }));
    expect(onRate).toHaveBeenCalledWith(4);
  });

  it("sends the last star chosen when the reader changes their mind", () => {
    const { onRate } = setup();
    fireEvent.click(star(5));
    fireEvent.click(star(2));
    fireEvent.click(screen.getByRole("button", { name: "Rate" }));
    expect(onRate).toHaveBeenCalledWith(2);
  });

  it("previews a hover without choosing it", () => {
    const { onRate } = setup();
    fireEvent.mouseEnter(star(3));
    fireEvent.mouseLeave(star(3));
    expect(screen.getByRole("button", { name: "Rate" })).toBeDisabled();
    expect(onRate).not.toHaveBeenCalled();
  });

  it("skips without rating", () => {
    const { onRate, onSkip } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Skip" }));
    expect(onSkip).toHaveBeenCalledTimes(1);
    expect(onRate).not.toHaveBeenCalled();
  });

  it("locks both buttons while the rating is being saved", () => {
    setup({ isSaving: true });
    expect(screen.getByRole("button", { name: "Skip" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Rate" })).toBeDisabled();
  });
});
