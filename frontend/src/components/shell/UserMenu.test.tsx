import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { USER_GUIDE_URL } from "@/lib/userGuide";
import type { User } from "@/types";
import { UserMenu } from "./UserMenu";

const USER = { full_name: "Anna Nowak", email: "anna@example.com" } as User;

describe("UserMenu", () => {
  it("leads to the About screen on every viewport, not only on the phone", async () => {
    // The licence and the source link are one click from the avatar; the
    // settings link beside them is hidden from `sm` up, this one is not.
    render(
      <MemoryRouter>
        <UserMenu user={USER} onLogout={vi.fn()} />
      </MemoryRouter>,
    );

    await userEvent.click(screen.getByRole("button", { name: "Anna Nowak" }));

    const about = screen.getByRole("menuitem", { name: "About" });
    expect(about).toHaveAttribute("href", "/settings/about");
    expect(about.closest(".sm\\:hidden")).toBeNull();
  });

  it("leads to the person's own profile on every viewport", async () => {
    render(
      <MemoryRouter>
        <UserMenu user={USER} onLogout={vi.fn()} />
      </MemoryRouter>,
    );

    await userEvent.click(screen.getByRole("button", { name: "Anna Nowak" }));

    const profile = screen.getByRole("menuitem", { name: "My profile" });
    expect(profile).toHaveAttribute("href", "/settings/profile");
    expect(profile.closest(".sm\\:hidden")).toBeNull();
  });

  it("opens the user guide in a new tab, so an invited member finds the manual", async () => {
    // Someone invited into an organization never sees the README; the
    // avatar menu is the one place every member opens.
    render(
      <MemoryRouter>
        <UserMenu user={USER} onLogout={vi.fn()} />
      </MemoryRouter>,
    );

    await userEvent.click(screen.getByRole("button", { name: "Anna Nowak" }));

    const guide = screen.getByRole("menuitem", { name: /User guide/ });
    expect(guide).toHaveAttribute("href", USER_GUIDE_URL);
    expect(guide).toHaveAttribute("target", "_blank");
    expect(guide).toHaveAttribute("rel", "noopener noreferrer");
    expect(guide.closest(".sm\\:hidden")).toBeNull();
  });

  it("offers the language picker the profile screen promises on a phone", async () => {
    // "The language picker in the header (in the account menu on a phone)":
    // the header's own picker is hidden below `sm`, so the menu is the only
    // place a phone reaches it from, and it has to be there under its name.
    render(
      <MemoryRouter>
        <UserMenu user={USER} onLogout={vi.fn()} />
      </MemoryRouter>,
    );

    await userEvent.click(screen.getByRole("button", { name: "Anna Nowak" }));

    const picker = screen.getByRole("button", { name: /^EN, Language:/ });
    expect(picker.closest(".sm\\:hidden")).not.toBeNull();
    await userEvent.click(picker);
    expect(screen.getByText("Deutsch")).toBeInTheDocument();
  });

  it.each(["My profile", "Settings", "About", /User guide/])(
    "closes the menu after %s is chosen, so it does not hang over the next screen",
    async (name) => {
      render(
        <MemoryRouter>
          <UserMenu user={USER} onLogout={vi.fn()} />
        </MemoryRouter>,
      );
      await userEvent.click(screen.getByRole("button", { name: "Anna Nowak" }));
      expect(screen.getByRole("menu")).toBeInTheDocument();

      await userEvent.click(screen.getByRole("menuitem", { name }));

      expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    },
  );

  it("closes the menu on a click elsewhere in the page, but not on a click inside it", async () => {
    render(
      <MemoryRouter>
        <p>Page content</p>
        <UserMenu user={USER} onLogout={vi.fn()} />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Anna Nowak" }));

    await userEvent.click(screen.getByText("anna@example.com"));
    expect(screen.getByRole("menu")).toBeInTheDocument();

    await userEvent.click(screen.getByText("Page content"));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("signs the person out from the menu", async () => {
    const onLogout = vi.fn();
    render(
      <MemoryRouter>
        <UserMenu user={USER} onLogout={onLogout} />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Anna Nowak" }));

    await userEvent.click(screen.getByRole("menuitem", { name: "Log out" }));

    expect(onLogout).toHaveBeenCalledTimes(1);
  });
});
