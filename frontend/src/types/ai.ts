/**
 * AI Connections types. The provider and capability unions are aliases of the
 * generated contract; the working shapes below stay hand-written because the
 * form holds states the wire does not (a blank input carries null, a masked
 * key never leaves the backend). See frontend/AGENTS.md, "Hand-written types
 * and the wire".
 */
import type { components } from "@/types/api-generated";

export type LlmProvider = components["schemas"]["LlmProvider"];

export type LlmCapability = components["schemas"]["LlmCapability"];

/**
 * The schema, with the two members the wire types loosely read as the unions
 * the UI branches on: `provider` and the capability names are plain strings
 * there, and `capability_checks` is an untyped dictionary. `capabilities`
 * stays optional, as the wire has it.
 */
export type AiConnection = Omit<
  components["schemas"]["AiConnectionDTO"],
  "provider" | "capabilities" | "capability_checks"
> & {
  provider: LlmProvider;
  capabilities?: LlmCapability[];
  /**
   * What the connection test found out, per capability. `capabilities` above
   * is the claim — often the form's guess from the provider's name; this is
   * what happened when the model was actually asked to do the job. A
   * capability missing here has never been tested.
   */
  capability_checks?: Partial<Record<LlmCapability, CapabilityCheck>>;
};

export interface CapabilityCheck {
  ok: boolean;
  at?: string | null;
  purpose?: string | null;
}

/**
 * The create payload as the FORM holds it: a blank input carries null, and
 * the backend reads null as "left empty". This is a working shape of its own,
 * not a copy of the generated `AiConnectionCreateDTO` — that one types
 * these fields as bare `string`, which cannot express the draft state
 * between "typed" and "left empty" the form lives in. The wire contract
 * accepts both shapes, which is why the draft carries its own name.
 */
export interface AiConnectionDraft {
  name: string;
  provider: LlmProvider;
  api_key?: string | null;
  api_base_url?: string | null;
  model_name?: string | null;
  temperature?: number | null;
  max_tokens?: number | null;
  top_p?: number | null;
  capabilities: LlmCapability[];
}

export type AiConnectionUpdate = components["schemas"]["AiConnectionUpdateDTO"];

/** The schema, with `capability` read as the union the UI branches on. */
export type AiPurpose = Omit<
  components["schemas"]["AiPurposeDTO"],
  "capability"
> & {
  capability: LlmCapability;
};

export interface AiBindingRequest {
  purpose_key: string;
  connection_id: string | null;
}

/**
 * What the connection test found. `verdict` is the answer; `contract` is the
 * evidence.
 *
 * A failed request (HTTP 400) is the fourth outcome — the provider never
 * answered at all — and arrives as a rejected promise, not as a verdict.
 */
export interface AiConnectionTestResult {
  ok: boolean;
  /** "ok" — the model delivered. "contract_failed" — it answered, but not in
   * the agreed shape. "unchecked" — nothing to probe this connection with. */
  verdict: "ok" | "contract_failed" | "unchecked";
  models: string[];
  contract: {
    checked: boolean;
    ok: boolean;
    purpose: string | null;
    attempts?: number;
    /** False means the shape was not forced on the wire — the answer rode on
     * the parser and one retry, so it can go wrong later. */
    schema_enforced: boolean;
    answer_preview?: string;
    error?: string;
    reason?: string;
    /** What the model made of the probe's reference label, field by field.
     *
     * The verdict answers "was the answer the agreed shape". Whether the
     * model also *read* the picture is a second question, and a green
     * verdict never answered it: a well-formed `{"name": "Milk"}` for a
     * carton labelled OAT DRINK passed like a real reading. Present only
     * when the answer parsed — there is nothing to compare otherwise. */
    reading?: {
      fields: Record<
        string,
        { expected: string; read: string | null; matches: boolean }
      >;
      matched: number;
      of: number;
    };
  };
}
