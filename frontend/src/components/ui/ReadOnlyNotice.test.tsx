import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReadOnlyNotice } from "./ReadOnlyNotice";

const rights = vi.hoisted(() => ({
  write: false,
  manage: false,
  read: true,
}));

vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => rights.write,
  useCanManage: () => rights.manage,
}));
vi.mock("@/hooks/useHasPermission", () => ({
  useHasPermission: (key: string) =>
    key.endsWith(":read") ? rights.read : false,
}));

/**
 * The `manage` boundary is held by whoever the organization lets manage the
 * module, not only by administrators — the production cancel tooltip says "ask
 * someone who can manage production", and this notice has to name the same
 * person instead of sending the reader to an administrator.
 */
describe("ReadOnlyNotice", () => {
  afterEach(() => {
    rights.read = true;
  });

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

  it("uses the read-only words when the reader cannot write either", () => {
    rights.write = false;
    rights.manage = false;
    render(<ReadOnlyNotice module="maker" right="manage" />);

    const note = screen.getByRole("note");
    expect(note).toHaveTextContent("You can view this, not change it");
    expect(note).not.toHaveTextContent(/can use this module/i);
  });

  it("says the module cannot be read to an account without the read permission", () => {
    rights.write = false;
    rights.read = false;
    render(<ReadOnlyNotice module="items" />);

    const note = screen.getByRole("note");
    expect(note).toHaveTextContent("You cannot open this");
    expect(note).toHaveTextContent(/administrator/i);
    expect(note).not.toHaveTextContent(/can read this module/);
  });

  it("says the module cannot be read even when only the manage right is missing", () => {
    rights.manage = false;
    rights.read = false;
    render(<ReadOnlyNotice module="maker" right="manage" />);

    expect(screen.getByRole("note")).toHaveTextContent("You cannot open this");
  });

  it("renders nothing for an account that holds the right", () => {
    rights.manage = true;
    const { container } = render(
      <ReadOnlyNotice module="maker" right="manage" />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
