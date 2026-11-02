import { render } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import LoadingSpinner from "./LoadingSpinner";

describe("LoadingSpinner", () => {
  it("should render correctly", () => {
    const { container } = render(<LoadingSpinner />);
    expect(container.firstChild).toHaveClass("flex");
    expect(container.querySelector(".animate-spin")).toBeInTheDocument();
  });
});
