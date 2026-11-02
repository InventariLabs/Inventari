import { describe, it, expect } from "vitest";

import {
  compare,
  fieldsOf,
  mirrorDeclarations,
} from "./check-mirrored-types.mjs";

describe("check-mirrored-types", () => {
  it("finds the interfaces that opted in", () => {
    const source = `
      /**
       * @mirrors components["schemas"]["AuditLogDTO"]
       */
      export interface AuditLogEntry {
        id: string;
      }
      export interface NotMirrored {
        id: string;
      }
    `;

    expect(mirrorDeclarations(source)).toEqual({
      AuditLogEntry: "AuditLogDTO",
    });
  });

  it("reads optionality and the stated type", () => {
    expect(fieldsOf(`  id: string;\n  reason?: string | null;`)).toEqual({
      id: { optional: false, type: "string" },
      reason: { optional: true, type: "string | null" },
    });
  });

  it("reports the three ways a mirror can lie", () => {
    const manual = {
      quantity: { optional: false, type: "number" },
      user_id: { optional: false, type: "string | null" },
      invented: { optional: false, type: "string" },
    };
    const wire = {
      quantity: { optional: false, type: "string" },
      user_id: { optional: true, type: "string | null" },
      missing_here: { optional: false, type: "string" },
    };

    expect(compare("X", manual, wire)).toEqual([
      "X.quantity: number here, string on the wire",
      "X.user_id: required here, optional on the wire",
      "X.invented: not on the wire at all",
      "X.missing_here: on the wire, missing here",
    ]);
  });
});
