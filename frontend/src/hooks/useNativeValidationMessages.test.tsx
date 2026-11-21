import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { act } from "react";
import i18n from "i18next";
import { useNativeValidationMessages } from "./useNativeValidationMessages";

function Form() {
  useNativeValidationMessages();
  return (
    <form>
      <label>
        Password
        <input type="password" required minLength={8} />
      </label>
      <label>
        Email
        <input type="email" />
      </label>
      <label>
        Host
        <input
          required
          ref={(el) => el?.setCustomValidity("The screen's own sentence")}
        />
      </label>
    </form>
  );
}

describe("useNativeValidationMessages", () => {
  it("words a missing value in the app's language, not the browser's", () => {
    render(<Form />);
    const password = screen.getByLabelText("Password") as HTMLInputElement;

    password.checkValidity();

    expect(password.validationMessage).toBe("Fill in this field");
  });

  it("asks for an email address in the app's language", () => {
    render(<Form />);
    const email = screen.getByLabelText("Email") as HTMLInputElement;
    fireEvent.input(email, { target: { value: "not an address" } });

    email.checkValidity();

    expect(email.validationMessage).toBe("Enter an email address");
  });

  it("hands the field back to the browser once it is edited", () => {
    render(<Form />);
    const password = screen.getByLabelText("Password") as HTMLInputElement;
    password.checkValidity();

    fireEvent.input(password, { target: { value: "long enough" } });

    expect(password.validity.customError).toBe(false);
    expect(password.checkValidity()).toBe(true);
  });

  it("leaves a sentence the screen set itself alone", () => {
    render(<Form />);
    const host = screen.getByLabelText("Host") as HTMLInputElement;

    host.checkValidity();
    fireEvent.input(host, { target: { value: "x" } });

    expect(host.validationMessage).toBe("The screen's own sentence");
  });

  it("releases a field marked before the app language changed", async () => {
    render(<Form />);
    const password = screen.getByLabelText("Password") as HTMLInputElement;
    password.checkValidity();

    await act(() => i18n.changeLanguage("pl"));
    try {
      fireEvent.input(password, { target: { value: "long enough" } });

      expect(password.validity.customError).toBe(false);
      expect(password.checkValidity()).toBe(true);
    } finally {
      await act(() => i18n.changeLanguage("en"));
    }
  });
});
