import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { RecordNotFound } from "./RecordNotFound";

const navigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return { ...actual, useNavigate: () => navigate };
});

const renderIt = () =>
  render(
    <MemoryRouter>
      <RecordNotFound
        title="Document not found"
        backTo="/warehouse"
        backLabel="Back to list"
      />
    </MemoryRouter>,
  );

describe("RecordNotFound", () => {
  it("names what was not found", () => {
    renderIt();
    expect(screen.getByText("Document not found")).toBeInTheDocument();
  });

  it("offers one way onwards, and it leads to the list", async () => {
    const user = userEvent.setup();
    renderIt();
    await user.click(screen.getByRole("button", { name: "Back to list" }));
    expect(navigate).toHaveBeenCalledWith("/warehouse");
  });

  it("does not offer a retry — a 404 does not become an answer by asking twice", () => {
    renderIt();
    expect(
      screen.queryByRole("button", { name: /retry|try again|ponów/i }),
    ).not.toBeInTheDocument();
  });
});
