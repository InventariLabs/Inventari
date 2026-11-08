import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * `Root` is the whole page under the one React root: the providers, then one
 * of the two trees, chosen by the address. The trees are stand-ins here; what
 * is pinned is where `Root` puts them.
 */
vi.mock("./App", async () => {
  const { useModules } = await import("./contexts/ModulesContext");
  return {
    default: function App() {
      // Throws outside a ModulesProvider, which is how the application
      // fails when it is mounted anywhere else.
      useModules();
      return <p>application</p>;
    },
  };
});
vi.mock("./PublicApp", () => ({
  default: () => <p>public page</p>,
}));

/**
 * The tree is chosen when `Root` is imported, so the address comes first. The
 * test setup replaces `window.location` with a plain object, which is why the
 * path is written into it rather than pushed onto the history.
 */
async function renderRootAt(path: string) {
  window.location.pathname = path;
  vi.resetModules();
  const { default: Root } = await import("./Root");
  render(<Root />);
}

describe("Root", () => {
  afterEach(() => {
    window.location.pathname = "/";
  });

  it("runs the application inside the modules provider", async () => {
    await renderRootAt("/");

    expect(await screen.findByText("application")).toBeInTheDocument();
  });

  it("serves a public address the public tree and not the application", async () => {
    await renderRootAt("/public/attestation/a-token");

    expect(await screen.findByText("public page")).toBeInTheDocument();
    expect(screen.queryByText("application")).not.toBeInTheDocument();
  });
});
