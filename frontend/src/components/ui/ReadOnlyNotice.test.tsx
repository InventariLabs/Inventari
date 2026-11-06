import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ReadOnlyNotice } from "./ReadOnlyNotice";

const rights = vi.hoisted(() => ({ write: false, manage: false }));

vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => rights.write,
  useCanManage: () => rights.manage,
}));
vi.mock("@/hooks/useHasPermission", () => ({ useHasPermission: () => false }));

/**
 * The `manage` boundary is held by whoever the organization lets manage the
 * module, not only by administrators — the production cancel tooltip says "ask
 * someone who can manage production", and this notice has to name the same
 * person instead of sending the reader to an administrator.
 */
describe("ReadOnlyNotice", () => {
  it("sends an account without the manage right to whoever can manage", () => {
    rights.write = true;
    rights.manage = false;
    render(<ReadOnlyNotice module="maker" right="manage" />);

    expect(screen.getByRole("note")).toHaveTextContent(
      /Ask someone who can manage it in your organization/,
    );
    expect(screen.getByRole("note")).not.toHaveTextContent(/administrator/i);
  });

  it("keeps the write notice for an account that cannot write", () => {
    rights.write = false;
    render(<ReadOnlyNotice module="maker" />);

    expect(screen.getByRole("note")).toHaveTextContent(
      "You can view this, not change it",
    );
  });

  it("renders nothing for an account that holds the right", () => {
    rights.manage = true;
    const { container } = render(
      <ReadOnlyNotice module="maker" right="manage" />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
