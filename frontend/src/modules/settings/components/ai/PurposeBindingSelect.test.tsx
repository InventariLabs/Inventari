import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { PurposeBindingSelect } from "@/modules/settings/components/ai/PurposeBindingSelect";
import { signInWith, signOut } from "@/test/auth";
import type { AiConnection, AiPurpose } from "@/types/ai";

// Binding a purpose is `org:settings:write` on the API; the select asks for
// it and these tests exercise the choosing.
beforeEach(() => signInWith(["org:settings:write"]));
afterEach(signOut);

const mutate = vi.fn();

vi.mock("@/modules/settings/hooks/useAiConnections", () => ({
  useSetAiBinding: () => ({
    mutate,
    isPending: false,
  }),
}));

const connections: AiConnection[] = [
  {
    id: "conn-1",
    name: "Vision pool",
    provider: "openrouter",
    api_key: "**********",
    api_base_url: "",
    model_name: "google/gemini-2.0-flash",
    temperature: null,
    max_tokens: null,
    top_p: null,
    capabilities: ["vision"],
    capability_checks: {},
    created_at: "",
    updated_at: "",
  },
  {
    id: "conn-2",
    name: "Text pool",
    provider: "custom",
    api_key: "",
    api_base_url: "http://localhost:11434/v1",
    model_name: "llama3.2",
    temperature: null,
    max_tokens: null,
    top_p: null,
    capabilities: ["text"],
    capability_checks: {},
    created_at: "",
    updated_at: "",
  },
];

describe("PurposeBindingSelect", () => {
  it("lists only connections matching the purpose capability", () => {
    const purpose: AiPurpose = {
      key: "vision.extract",
      label_key: "vision:ai.purposeLabel",
      description_key: "vision:ai.purposeDesc",
      owner_module: "vision",
      capability: "vision",
      bound_connection_id: null,
      usable: false,
    };

    render(
      <PurposeBindingSelect purpose={purpose} connections={connections} />,
    );

    expect(
      screen.getByRole("option", { name: /Vision pool/i }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Text pool/i })).toBeNull();
  });

  it("preselects the currently bound connection", () => {
    const purpose: AiPurpose = {
      key: "vision.extract",
      label_key: "vision:ai.purposeLabel",
      description_key: "vision:ai.purposeDesc",
      owner_module: "vision",
      capability: "vision",
      bound_connection_id: "conn-1",
      usable: true,
    };

    render(
      <PurposeBindingSelect purpose={purpose} connections={connections} />,
    );

    expect(
      (
        screen.getByRole("option", {
          name: /Vision pool/i,
        }) as HTMLOptionElement
      ).selected,
    ).toBe(true);
  });

  it("emits a new connection_id on change", async () => {
    mutate.mockClear();

    const purpose: AiPurpose = {
      key: "vision.extract",
      label_key: "vision:ai.purposeLabel",
      description_key: "vision:ai.purposeDesc",
      owner_module: "vision",
      capability: "vision",
      bound_connection_id: null,
      usable: false,
    };

    const user = userEvent.setup();
    render(
      <PurposeBindingSelect purpose={purpose} connections={connections} />,
    );

    await user.selectOptions(
      screen.getByRole("combobox"),
      screen.getByRole("option", { name: /Vision pool/i }),
    );

    expect(mutate).toHaveBeenCalledWith({
      purpose_key: "vision.extract",
      connection_id: "conn-1",
    });
  });

  /**
   * The purpose used to be labelled `RECIPES.TEXT_PARSE` — its own identifier,
   * shouted by an `uppercase` class, because `recipes:ai.purposeLabel` existed
   * in no catalog and the fallback is the key.
   */
  it("names the purpose rather than printing its key", () => {
    const purpose: AiPurpose = {
      key: "recipes.text_parse",
      label_key: "recipes:ai.purposeLabel",
      description_key: "recipes:ai.purposeDesc",
      owner_module: "recipes",
      capability: "text",
      bound_connection_id: null,
      usable: false,
    };

    render(
      <MemoryRouter>
        <PurposeBindingSelect purpose={purpose} connections={connections} />
      </MemoryRouter>,
    );

    expect(screen.queryByText(/text_parse/i)).toBeNull();
    expect(screen.getByText(/read a recipe from text/i)).toBeInTheDocument();
    expect(
      screen.getByText(/ingredients, quantities and steps/i),
    ).toBeInTheDocument();
  });

  /** A dead end otherwise: connections are created two sections away. */
  it("points at where a connection is created when there is none to pick", () => {
    const purpose: AiPurpose = {
      key: "recipes.text_parse",
      label_key: "recipes:ai.purposeLabel",
      description_key: "recipes:ai.purposeDesc",
      owner_module: "recipes",
      capability: "text",
      bound_connection_id: null,
      usable: false,
    };

    // Only the vision connection exists, so nothing answers for text — the
    // state seen in the running app, with the warning and no way out of it.
    render(
      <MemoryRouter>
        <PurposeBindingSelect
          purpose={purpose}
          connections={connections.filter((c) =>
            c.capabilities?.includes("vision"),
          )}
        />
      </MemoryRouter>,
    );

    expect(screen.getByRole("link")).toHaveAttribute("href", "/settings/ai");
  });

  /** A purpose belongs to a module; with the module off, binding it is a
   *  setting that governs nothing that runs. */
  it("says so when the module that declared the purpose is switched off", () => {
    const purpose: AiPurpose = {
      key: "recipes.text_parse",
      label_key: "recipes:ai.purposeLabel",
      description_key: "recipes:ai.purposeDesc",
      owner_module: "recipes",
      capability: "text",
      bound_connection_id: null,
      usable: false,
    };

    render(
      <MemoryRouter>
        <PurposeBindingSelect
          purpose={purpose}
          connections={connections}
          available={false}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText(/module off/i)).toBeInTheDocument();
    expect(screen.getByRole("combobox")).toBeDisabled();
    // The "set one up" link belongs to a purpose that can be answered.
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("disables the select for an account without org:settings:write", () => {
    // Binding is an organization setting; a reader may see the choice and
    // not make it. Before, the change was accepted locally and refused by
    // the API.
    signOut();
    const purpose: AiPurpose = {
      key: "vision.extract",
      label_key: "vision:ai.purposeLabel",
      description_key: "vision:ai.purposeDesc",
      owner_module: "vision",
      capability: "vision",
      bound_connection_id: null,
      usable: false,
    };

    render(
      <MemoryRouter>
        <PurposeBindingSelect purpose={purpose} connections={connections} />
      </MemoryRouter>,
    );

    expect(screen.getByRole("combobox")).toBeDisabled();
    expect(
      screen.getByText(/your account can read this module/i),
    ).toBeInTheDocument();
  });

  it("offers no such link once a connection exists", () => {
    const purpose: AiPurpose = {
      key: "vision.extract",
      label_key: "vision:ai.purposeLabel",
      description_key: "vision:ai.purposeDesc",
      owner_module: "vision",
      capability: "vision",
      bound_connection_id: null,
      usable: false,
    };

    render(
      <MemoryRouter>
        <PurposeBindingSelect purpose={purpose} connections={connections} />
      </MemoryRouter>,
    );

    expect(screen.queryByRole("link")).toBeNull();
  });
});

describe("whose purpose this is", () => {
  it("names the module that asked for it", () => {
    // The purposes read as one flat list. Two phrased alike gave no way to
    // tell whose setting was whose, and the recipes module used to render a
    // second copy of its own on the same screen under another heading.
    const purpose: AiPurpose = {
      key: "recipes.text_parse",
      label_key: "recipes:ai.purposeLabel",
      description_key: "recipes:ai.purposeDesc",
      owner_module: "recipes",
      capability: "text",
      bound_connection_id: null,
      usable: false,
    };

    render(
      <MemoryRouter>
        <PurposeBindingSelect purpose={purpose} connections={connections} />
      </MemoryRouter>,
    );

    expect(screen.getByText(/recipes/i)).toBeInTheDocument();
  });
});

describe("PurposeBindingSelect — telling the options apart", () => {
  const visionPurpose: AiPurpose = {
    key: "vision.extract",
    label_key: "vision:ai.purposeLabel",
    description_key: "vision:ai.purposeDesc",
    owner_module: "vision",
    capability: "vision",
    bound_connection_id: null,
    usable: false,
  };

  const conn = (over: Partial<AiConnection>): AiConnection => ({
    id: "c",
    name: "c",
    provider: "minimax",
    api_key: "",
    api_base_url: "",
    model_name: "MiniMax-M3",
    temperature: null,
    max_tokens: null,
    top_p: null,
    capabilities: ["vision"],
    capability_checks: {},
    created_at: "",
    updated_at: "",
    ...over,
  });

  const renderWith = (connections: AiConnection[]) =>
    render(
      <MemoryRouter>
        <PurposeBindingSelect
          purpose={visionPurpose}
          connections={connections}
        />
      </MemoryRouter>,
    );

  it("does not say the same thing twice", () => {
    // The reported line was "minimax m3 · MiniMax-M3": one value, written
    // twice, with no sign of what distinguished it from its neighbour.
    renderWith([conn({ id: "c1", name: "minimax m3" })]);

    const option = screen.getByRole("option", { name: /minimax m3/i });
    expect(option.textContent).to.equal("minimax m3");
  });

  it("names the provider when the connection's own name does not", () => {
    renderWith([conn({ id: "c1", name: "Label reader", provider: "minimax" })]);

    expect(
      screen.getByRole("option", {
        name: "MiniMax · Label reader · MiniMax-M3",
      }),
    ).toBeInTheDocument();
  });

  it("keeps two connections to one model apart", () => {
    renderWith([
      conn({ id: "c1", name: "minimax" }),
      conn({ id: "c2", name: "minimax m3" }),
    ]);

    const labels = screen
      .getAllByRole("option")
      .map((o) => o.textContent)
      .filter((label) => label !== "Not configured");
    expect(new Set(labels).size).to.equal(labels.length);
  });

  it("leaves out a connection whose test for this capability failed", () => {
    // The backend refuses to hand it out, so offering it here would only
    // produce "nothing is configured" later, from a screen where something
    // plainly was.
    renderWith([
      conn({
        id: "c1",
        name: "Blind model",
        capability_checks: { vision: { ok: false } },
      }),
    ]);

    expect(screen.queryByRole("option", { name: /Blind model/ })).toBeNull();
    expect(screen.getByText(/Blind model/)).toBeInTheDocument();
  });

  it("keeps the org's choice detachable even when the verdict refuses it", async () => {
    // The state seen in the running app: the bound connection fails its
    // test, so the verdict refuses it — and when the option list followed
    // the verdict too, the raw binding named an option that was not there.
    // The browser then falls back to rendering "Not configured" as already
    // chosen, no change event can ever fire, and the binding can be
    // neither detached nor the connection deleted: a dead end with no way
    // out in the UI. The org's choice stays on its own list, refused or
    // not, so the select renders it and "Not configured" is a real choice.
    mutate.mockClear();
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <PurposeBindingSelect
          purpose={{
            ...visionPurpose,
            bound_connection_id: "c1",
            usable: false,
          }}
          connections={[
            conn({
              id: "c1",
              name: "Blind model",
              capability_checks: { vision: { ok: false } },
            }),
          ]}
        />
      </MemoryRouter>,
    );

    // The refused connection is on the list — bound to it — and the select
    // renders the org's choice, not "Not configured".
    expect(
      screen.getByRole("option", { name: /Blind model/ }),
    ).toBeInTheDocument();
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select.value).toBe("c1");

    // And the way out works: choosing "Not configured" detaches the
    // refused binding, which unblocks deleting the connection.
    await user.selectOptions(
      select,
      screen.getByRole("option", { name: /Not configured/i }),
    );
    expect(mutate).toHaveBeenCalledWith({
      purpose_key: "vision.extract",
      connection_id: null,
    });
  });
});

describe("a purpose the server's default model serves", () => {
  const textPurpose = (over: Partial<AiPurpose>): AiPurpose => ({
    key: "recipes.text_parse",
    label_key: "recipes:ai.purposeLabel",
    description_key: "recipes:ai.purposeDesc",
    owner_module: "recipes",
    capability: "text",
    bound_connection_id: null,
    usable: false,
    ...over,
  });

  const renderPurpose = (purpose: AiPurpose, list: AiConnection[] = []) =>
    render(
      <MemoryRouter>
        <PurposeBindingSelect purpose={purpose} connections={list} />
      </MemoryRouter>,
    );

  it("says the server default serves it instead of 'not configured'", () => {
    // No binding, usable: the env default runs this purpose. The select used
    // to read "Not configured" and offer to set up a connection while recipe
    // text parsing worked.
    renderPurpose(textPurpose({ usable: true }));

    expect(
      screen.getByRole("option", { name: "Server default model" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Not configured")).toBeNull();
    expect(screen.getByText(/default model/i, { selector: "p" })).toBeVisible();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("keeps today's sentences when nothing serves the purpose", () => {
    renderPurpose(textPurpose({ usable: false }));

    expect(
      screen.getByRole("option", { name: "Not configured" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/default model/i)).toBeNull();
    expect(screen.getByRole("link")).toBeInTheDocument();
  });

  it("shows the binding, not the server default, when one is chosen", () => {
    renderPurpose(
      textPurpose({ usable: true, bound_connection_id: "conn-2" }),
      [connections[1]],
    );

    expect(
      (screen.getByRole("option", { name: /Text pool/i }) as HTMLOptionElement)
        .selected,
    ).toBe(true);
    expect(screen.queryByText(/default model/i, { selector: "p" })).toBeNull();
  });
});
