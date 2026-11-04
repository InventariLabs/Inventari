import { afterEach, describe, expect, it } from "vitest";
import { render, screen } from "@/test/utils";
import { signInWith, signOut } from "@/test/auth";
import { HiddenRecordsNotice } from "./HiddenRecordsNotice";

afterEach(() => signOut());

function renderNotice() {
  render(
    <HiddenRecordsNotice
      message="2 locations are hidden — turn on Module data in Settings to see them."
      actionLabel="Open settings"
    />,
  );
}

describe("HiddenRecordsNotice", () => {
  it("links an administrator to the switch", () => {
    signInWith(["admin:access"]);
    renderNotice();

    expect(
      screen.getByRole("button", { name: "Open settings" }),
    ).toBeInTheDocument();
  });

  it("tells anyone else who can turn the switch on instead of sending them to a page that refuses them", () => {
    signInWith(["locations:read"]);
    renderNotice();

    expect(
      screen.queryByRole("button", { name: "Open settings" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/Only an administrator can turn this on/),
    ).toBeInTheDocument();
  });
});
