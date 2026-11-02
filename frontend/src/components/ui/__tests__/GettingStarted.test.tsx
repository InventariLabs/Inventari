import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, it, expect, vi } from "vitest";
import { signInWith, signOut } from "@/test/auth";
import { GettingStarted } from "@/components/ui/GettingStarted";

const steps = (onCta: () => void) => [
  { title: "One", ctaLabel: "Go to the form", ctaTo: "/form" },
  { title: "Two", ctaLabel: "Import from file", onCta },
];

describe("GettingStarted CTAs", () => {
  beforeEach(() => {
    signInWith(["equipment:write"]);
  });

  afterEach(() => {
    signOut();
  });

  it("renders a CTA with a target as a link", () => {
    render(<GettingStarted moduleName="equipment" steps={steps(vi.fn())} />);
    expect(
      screen.getByRole("link", { name: "Go to the form" }),
    ).toHaveAttribute("href", "/form");
  });

  it("renders a callback-only CTA as a button the keyboard can reach", async () => {
    const user = userEvent.setup();
    const onCta = vi.fn();
    render(<GettingStarted moduleName="equipment" steps={steps(onCta)} />);

    // An <a> without href is neither a link nor a tab stop.
    const button = screen.getByRole("button", { name: "Import from file" });
    await user.tab();
    await user.tab();
    expect(button).toHaveFocus();

    await user.keyboard("{Enter}");
    expect(onCta).toHaveBeenCalledTimes(1);
  });

  it("makes a lone callback CTA the primary action", () => {
    render(
      <GettingStarted
        moduleName="equipment"
        steps={[{ title: "One", ctaLabel: "Create", onCta: vi.fn() }]}
      />,
    );
    expect(screen.getByTestId("getting-started-cta")).toHaveRole("button");
  });

  it("offers an account that cannot write no CTA at all", () => {
    signInWith(["equipment:read"]);
    render(<GettingStarted moduleName="equipment" steps={steps(vi.fn())} />);

    expect(screen.getByText("One")).toBeInTheDocument();
    expect(screen.queryByTestId("getting-started-cta")).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
