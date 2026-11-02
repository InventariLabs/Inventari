import { describe, it, expect, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { signInWith, signOut } from "@/test/auth";
import { MissingRecipeNotice } from "./MissingRecipeNotice";

function renderNotice() {
  render(
    <MemoryRouter>
      <MissingRecipeNotice />
    </MemoryRouter>,
  );
}

describe("MissingRecipeNotice", () => {
  afterEach(() => signOut());

  it("leads a manager to where a formula is created", () => {
    signInWith(["maker:read", "maker:write", "maker:manage"]);
    renderNotice();

    expect(screen.getByRole("alert")).toHaveTextContent(/no BOM/i);
    expect(screen.getByTestId("missing-recipe-create-link")).toHaveAttribute(
      "href",
      "/maker",
    );
  });

  it("says there is no formula but leads a member nowhere they cannot save", () => {
    signInWith(["maker:read", "maker:write"]);
    renderNotice();

    expect(screen.getByRole("alert")).toHaveTextContent(/no BOM/i);
    expect(
      screen.queryByTestId("missing-recipe-create-link"),
    ).not.toBeInTheDocument();
  });
});
