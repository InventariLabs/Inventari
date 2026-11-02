/**
 * An upload leaves as an upload, whoever wrote the call.
 *
 * The shared instance declares `Content-Type: application/json`, and axios
 * reads that header before it looks at the body: a `FormData` payload sent
 * under a JSON content type is not sent as multipart at all — axios runs it
 * through `formDataToJSON` and posts an object. A `File` has no JSON form,
 * so the field simply disappears and the server answers 422 "this field is
 * required" about a file the user definitely picked.
 *
 * Eleven of the twelve upload helpers in this app passed the multipart
 * header by hand and were fine. The twelfth did not, and the organization
 * logo could not be uploaded from the interface at all. Remembering a
 * header at every call site is not a rule, it is a coin flip.
 *
 * Tested on the interceptor rather than through the mock server on
 * purpose: jsdom's XHR does not put a real multipart body on the wire, so a
 * round trip would be measuring the test environment. What the request
 * actually looks like in a browser is checked by opening the screen.
 */
import { describe, expect, it } from "vitest";
import { AxiosHeaders, type InternalAxiosRequestConfig } from "axios";
import { applyRequestHeaders } from "./client";

const configWith = (data: unknown): InternalAxiosRequestConfig =>
  ({
    headers: new AxiosHeaders({ "Content-Type": "application/json" }),
    data,
  }) as InternalAxiosRequestConfig;

describe("the request interceptor and a form body", () => {
  it("drops the JSON content type when the body is a form", () => {
    const form = new FormData();
    form.append(
      "image",
      new File(["pixels"], "logo.png", { type: "image/png" }),
    );

    const config = applyRequestHeaders(configWith(form));

    expect(config.headers.get("Content-Type")).toBeUndefined();
  });

  it("leaves an ordinary JSON body's content type alone", () => {
    const config = applyRequestHeaders(configWith({ name: "Widget" }));

    expect(config.headers.get("Content-Type")).toBe("application/json");
  });

  it("still sets the language on a form request", () => {
    const config = applyRequestHeaders(configWith(new FormData()));

    expect(config.headers["Accept-Language"]).toBeTruthy();
  });
});
