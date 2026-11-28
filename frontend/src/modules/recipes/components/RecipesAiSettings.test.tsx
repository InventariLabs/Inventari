/**
 * The recipes AI card offers both purposes the module owns.
 *
 * The reader key is a connection, bound per purpose like every other
 * credential, so the card offers both slots: the parser and the page reader. A
 * card that offered only the parser would send the reader key back to whatever
 * screen happened to be nearest.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { RecipesAiSettings } from "./RecipesAiSettings";

const mockPurposes = vi.hoisted(() => ({
  purposes: [
    {
      key: "recipes.text_parse",
      capability: "text",
      label_key: "recipes:ai.purposeLabel",
      description_key: "recipes:ai.purposeDesc",
      owner_module: "recipes",
      bound_connection_id: null,
      usable: false,
      server_default: false,
    },
    {
      key: "recipes.url_fetch",
      capability: "url_fetch",
      label_key: "recipes:ai.urlFetchPurposeLabel",
      description_key: "recipes:ai.urlFetchPurposeDesc",
      owner_module: "recipes",
      bound_connection_id: null,
      usable: false,
      server_default: false,
    },
  ],
  connections: [],
  failed: false,
  refetch: vi.fn(),
}));

vi.mock("@/modules/settings/hooks/useAiConnections", () => ({
  useAiConnections: () => ({
    data: mockPurposes.failed ? undefined : mockPurposes.connections,
    isError: false,
    refetch: mockPurposes.refetch,
  }),
  useAiPurposes: () => ({
    data: mockPurposes.failed ? undefined : mockPurposes.purposes,
    isError: mockPurposes.failed,
    refetch: mockPurposes.refetch,
  }),
  useSetAiBinding: () => ({ mutate: vi.fn() }),
}));

// No react-i18next mock on purpose: the suite runs the real i18next, so
// the assertions below read the words the screen renders — a `t: (key) =>
// key` stand-in would pass with the catalog missing the key entirely.

describe("RecipesAiSettings", () => {
  it("offers the parser and the page reader, one slot each", () => {
    render(
      <MemoryRouter>
        <RecipesAiSettings />
      </MemoryRouter>,
    );

    expect(screen.getAllByText(/read a recipe from text/i).length).toBe(1);
    expect(screen.getAllByText(/read a recipe from a web page/i).length).toBe(
      1,
    );
    expect(screen.getAllByRole("combobox").length).toBe(2);
  });

  it("keeps rendering when the backend has not registered the reader yet", () => {
    const { rerender } = render(
      <MemoryRouter>
        <RecipesAiSettings />
      </MemoryRouter>,
    );
    mockPurposes.purposes.pop();
    rerender(
      <MemoryRouter>
        <RecipesAiSettings />
      </MemoryRouter>,
    );

    expect(screen.getAllByText(/read a recipe from text/i).length).toBe(1);
    expect(
      screen.queryByText(/read a recipe from a web page/i),
    ).not.toBeInTheDocument();
    expect(screen.getAllByRole("combobox").length).toBe(1);
  });

  it("says the registry did not load, with a retry, instead of 'bind it in the main settings'", () => {
    mockPurposes.failed = true;
    render(
      <MemoryRouter>
        <RecipesAiSettings />
      </MemoryRouter>,
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(mockPurposes.refetch).toHaveBeenCalledTimes(1);
    mockPurposes.failed = false;
  });
});
