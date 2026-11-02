import React from "react";
import { vi } from "vitest";

vi.mock("lucide-react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("lucide-react")>();

  interface MockLucideIconProps extends React.SVGProps<SVGSVGElement> {
    size?: number | string;
  }
  const MockIcon = React.forwardRef<SVGSVGElement, MockLucideIconProps>(
    (props, ref) =>
      React.createElement("svg", {
        ref,
        width: props.size || 24,
        height: props.size || 24,
        ...props,
      }),
  );

  return new Proxy(actual, {
    get: (target, prop: string) => {
      if (prop === "__esModule") return true;
      if (
        typeof target[prop as keyof typeof target] === "function" ||
        target[prop as keyof typeof target] !== undefined
      ) {
        return target[prop as keyof typeof target];
      }
      return MockIcon;
    },
  });
});
