import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";

describe("Button", () => {
  it("renders children text", () => {
    render(<Button>Click me</Button>);
    expect(
      screen.getByRole("button", { name: "Click me" }),
    ).toBeInTheDocument();
  });

  it("calls onClick handler", () => {
    const handleClick = vi.fn();
    render(<Button onClick={handleClick}>Click</Button>);
    fireEvent.click(screen.getByRole("button"));
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it("is disabled when disabled prop is set", () => {
    render(<Button disabled>Disabled</Button>);
    expect(screen.getByRole("button")).toBeDisabled();
  });

  it("is disabled during loading state", () => {
    render(<Button isLoading>Submit</Button>);
    expect(screen.getByRole("button")).toBeDisabled();
  });

  it("keeps its label while loading, and swaps the leading icon for a spinner", () => {
    // A button that becomes a bare spinner stops saying what is taking time;
    // on the SMTP test that dot used to spin for two minutes with no label.
    const LeftIcon = () => <span data-testid="left-icon" />;
    const { container } = render(
      <Button isLoading leftIcon={<LeftIcon />}>
        Submit
      </Button>,
    );
    expect(screen.getByText("Submit")).toBeInTheDocument();
    expect(screen.queryByTestId("left-icon")).not.toBeInTheDocument();
    expect(container.querySelector(".animate-spin")).toBeInTheDocument();
  });

  it("renders with leftIcon and rightIcon", () => {
    const LeftIcon = () => <span data-testid="left-icon" />;
    const RightIcon = () => <span data-testid="right-icon" />;
    render(
      <Button leftIcon={<LeftIcon />} rightIcon={<RightIcon />}>
        Label
      </Button>,
    );
    expect(screen.getByTestId("left-icon")).toBeInTheDocument();
    expect(screen.getByTestId("right-icon")).toBeInTheDocument();
  });

  it.each([
    "primary",
    "secondary",
    "outline",
    "ghost",
    "danger",
    "ghostDanger",
    "success",
  ] as const)('renders variant "%s" without throwing', (variant) => {
    const { container } = render(<Button variant={variant}>Test</Button>);
    expect(container.querySelector("button")).toBeInTheDocument();
  });

  it("colours a low-emphasis destructive action at rest, not on hover", () => {
    render(<Button variant="ghostDanger">Deactivate</Button>);
    const button = screen.getByRole("button", { name: "Deactivate" });
    // The whole point of the variant: on a touch screen there is no hover, so
    // a warning that only appears on hover arrives after the tap.
    expect(button.className).toContain("text-on-danger");
    expect(button.className).not.toContain("hover:text-");
  });

  // Measured white-on-background ratios — none of these ramp steps is remapped
  // in `.dark` by index.css, so a filled button renders the same in either
  // theme (the primary fill's dark-theme step is pinned separately below).
  // 4.5:1 is the AA floor for the 12-14px labels these sizes use.
  //   primary-700 5.47:1 · red-600 4.83:1 · success-800 7.68:1
  it.each([
    [
      "default",
      "bg-primary-700",
      "hover:bg-primary-800",
      "active:bg-primary-900",
    ],
    [
      "primary",
      "bg-primary-700",
      "hover:bg-primary-800",
      "active:bg-primary-900",
    ],
    ["destructive", "bg-red-600", "hover:bg-red-700", "active:bg-red-800"],
    ["danger", "bg-red-600", "hover:bg-red-700", "active:bg-red-800"],
    [
      "success",
      "bg-success-800",
      "hover:bg-success-900",
      "active:bg-success-900",
    ],
  ] as const)(
    'filled variant "%s" carries white text on a background that clears AA',
    (variant, background, hover, active) => {
      render(<Button variant={variant}>Save</Button>);
      const button = screen.getByRole("button", { name: "Save" });
      expect(button.className).toContain(background);
      expect(button.className).toContain(hover);
      // The press step continues one ramp shade down; the palette runs out at
      // 900 for success, which holds its hover shade for the press.
      expect(button.className).toContain(active);
      expect(button.className).toContain("text-white");
    },
  );

  // A product profile's palette takes its 700 step to the ramp's 400 under
  // `.dark` (useProfileTheme) so that text in primary-700 reads on a dark card.
  // A fill on that step turns into the light shade: white on it measured
  // 1.92:1 on every Food & Home button. 800 passes through, so the primary
  // fill moves to it in dark — the ratio itself is pinned in useProfileTheme.
  it.each(["default", "primary"] as const)(
    'primary-fill variant "%s" leaves the profile-remapped 700 step in dark',
    (variant) => {
      render(<Button variant={variant}>Save</Button>);
      const { className } = screen.getByRole("button", { name: "Save" });
      expect(className).toContain("dark:bg-primary-800");
      expect(className).toContain("dark:hover:bg-primary-900");
    },
  );

  // `success-700` and `accent-700` are remapped in `.dark` to the bright shade
  // so that *text* clears AA on a dark card. That makes the step unusable as a
  // filled background: it would render white on rgb(16 185 129) — 2.54:1.
  it("keeps the success variant off the ramp step reserved for text", () => {
    render(<Button variant="success">Confirm</Button>);
    const button = screen.getByRole("button", { name: "Confirm" });
    expect(button.className).not.toContain("bg-success-700");
    expect(button.className).not.toContain("bg-success-500");
  });

  it("applies a keyboard focus ring via focus-visible classes", () => {
    render(<Button>Focus me</Button>);
    const button = screen.getByRole("button", { name: "Focus me" });
    expect(button.className).toContain("focus-visible:outline-none");
    expect(button.className).toContain("focus-visible:ring-2");
    expect(button.className).toContain("focus-visible:ring-ring");
    expect(button.className).toContain("focus-visible:ring-offset-background");
  });
  it.each(["iconSm", "inline"] as const)(
    'size "%s" carries no responsive geometry',
    (size) => {
      render(<Button size={size}>x</Button>);
      const cls = screen.getByRole("button").className;
      expect(cls).not.toMatch(/\bmd:[hw]-/);
    },
  );

  it("keeps the 44px touch target on the plain icon size", () => {
    render(<Button size="icon">x</Button>);
    const cls = screen.getByRole("button").className;
    expect(cls).toContain("h-11");
    expect(cls).toContain("md:h-10");
  });

  it("documents why a smaller icon button is a size, not a className", () => {
    // twMerge does not strip a class carrying a responsive modifier when the
    // override has none — so `size="icon"` + `className="h-8 w-8"` renders 32px
    // below md and 40px on every desktop. This is the trap the two sizes above
    // exist to close; if this ever stops holding, they can be reconsidered.
    expect(cn("h-11 w-11 md:h-10 md:w-10", "h-8 w-8")).toContain("md:h-10");
    expect(
      cn("h-11 w-11 md:h-10 md:w-10", "h-8 w-8 md:h-8 md:w-8"),
    ).not.toContain("md:h-10");
  });

  it("lets a row take its height from its content, at every width", () => {
    render(<Button size="row">row</Button>);
    const cls = screen.getByRole("button").className;

    expect(cls).toContain("h-auto");
    // The point of the size: nothing here may pin a height above `md`, or the
    // row is clipped to 40px on a desktop and its own content overlaps.
    expect(cls).not.toMatch(/\bmd:h-/);
  });

  it("keeps a row's padding overridable, since it is not pinned responsively", () => {
    render(
      <Button size="row" className="px-4 py-4">
        row
      </Button>,
    );
    const cls = screen.getByRole("button").className;

    expect(cls).toContain("py-4");
    expect(cls).not.toContain("py-3");
  });
});
