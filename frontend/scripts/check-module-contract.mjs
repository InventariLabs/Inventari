#!/usr/bin/env node
/**
 * check-module-contract.mjs
 *
 * The frontend module interface is a published contract. A module outside this
 * repository registers a `FrontendModule`, contributes a component to a slot by
 * name with the props `SlotDataMap` declares, and reads the slot table in
 * `docs/FRONTEND_MODULE_GUIDE.md` to learn what it may register into. Until
 * this gate existed, nothing recorded that contract: renaming a slot or a
 * field, or changing a prop's type, compiled every in-tree module in the same
 * commit (they were repaired together) and broke an external module where it
 * was written, not here.
 *
 * The policy mirrors the backend's DTO and core-API snapshots, because the
 * failure is the same shape:
 *
 *   - removed or renamed slot / field                       -> error
 *   - a field's type changed                                -> error
 *   - optional field becoming required                      -> error
 *   - a new *required* field, at any depth                  -> error
 *
 * Additions pass silently: a new slot, a new `FrontendModule` field, a new
 * optional field, a union member added, an optional parameter added, and
 * required -> optional relaxations. A module may ignore anything it does not
 * use; a slot receives extra data without its contributor changing. A union
 * member that disappears is a break even when another appears in its place:
 * `undefined` swapped for `null` leaves a module testing for the old one with
 * no value it recognises.
 *
 * The snapshot records *shapes*, not the spelling of a type annotation. A
 * `ModuleRoute.path` that became a number and a `ScannedTemplate.name` that
 * became a number both keep the annotation `ModuleRoute[]` / `ScannedTemplate`
 * — the contract changed without the source text saying so. So every named
 * type reachable from the two contract files is expanded through the
 * TypeScript checker: the fields a module and a slot contributor actually
 * read, at every level. Two boundaries stop the expansion where the promise
 * belongs to somebody else:
 *
 *   - a type declared outside this checkout (React's `ComponentType`,
 *     `LucideIcon`, the TypeScript lib) is recorded by name and type
 *     arguments. Its shape is not this repository's to promise.
 *   - a wire schema generated into `src/types/api-generated.ts` is recorded by
 *     the schema it names (`{ "schema": "Item" }`). That file is the backend's
 *     published contract, frozen by `make check-api-types` and the backend's
 *     DTO snapshot; copying it here would churn this snapshot on every backend
 *     field and say nothing the wire gate has not already said. Re-pointing a
 *     frontend alias at another schema still changes the recorded name.
 *
 * The guide's table is checked against the same map. The table names every slot
 * that exists and no other, each row lists every prop the slot carries and no
 * other, marked optional (`name?`) exactly when the type makes it optional, and
 * its status matches whether an in-tree module contributes to the slot today.
 * A row that listed a subset passed for a long time: the approval status badge
 * showed two of its eight props, and an author learned of the other six from
 * the source.
 * The prose in the other columns stays hand-written, because a slot's render
 * location is not something the type can say.
 *
 * Modes:
 *   node check-module-contract.mjs                  verify snapshot + guide
 *   node check-module-contract.mjs --write-snapshot refresh the snapshot
 *   node check-module-contract.mjs --guide          check the guide only
 *
 * Run from the host (or where both trees are visible) when changing a slot:
 * the frontend container mounts only `frontend/`, so the guide check is skipped
 * there, exactly like the module-catalog snapshot.
 */
import {
  existsSync,
  readFileSync,
  readdirSync,
  writeFileSync,
} from "node:fs";
import { relative, resolve } from "node:path";
import ts from "typescript";

// `import.meta.dirname`, not `new URL("..", import.meta.url)`: under vitest
// vite rewrites that expression as an asset URL, and its path is not this
// directory's parent.
const ROOT = resolve(import.meta.dirname, ".."); // frontend/
const INTERFACES_PATH = resolve(
  ROOT,
  "src/lib/moduleRegistry/moduleInterfaces.ts",
);
const SLOTS_PATH = resolve(ROOT, "src/lib/moduleRegistry/slotProps.ts");
const SNAPSHOT_PATH = resolve(ROOT, "scripts/module-contract.json");
const GUIDE_PATH = resolve(ROOT, "../docs/FRONTEND_MODULE_GUIDE.md");
const MODULES_PATH = resolve(ROOT, "src/modules");
const GENERATED_TYPES_PATH = resolve(ROOT, "src/types/api-generated.ts");
// The snapshot format changed from annotation text to resolved shapes, so a
// version-1 file cannot be compared against this one.
const SNAPSHOT_VERSION = 2;

const GUIDE_HEADING = "### Complete Slot Reference";
const GUIDE_NEXT_HEADING = "\n> **Status semantics";

/**
 * Compiler options for the contract program. `paths` and `moduleResolution`
 * come from `tsconfig.json`, so `@/types` resolves the way it does in the
 * build; the program is rooted at the two contract files only, so this reads
 * the declarations the contract reaches rather than the whole application.
 */
function compilerOptions() {
  const config = ts.readConfigFile(resolve(ROOT, "tsconfig.json"), ts.sys.readFile);
  if (config.error)
    throw new Error(
      `cannot read tsconfig.json: ${ts.flattenDiagnosticMessageText(
        config.error.messageText,
        " ",
      )}`,
    );
  const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, ROOT);
  return { ...parsed.options, noEmit: true };
}

/**
 * A program over `sources` (`{ absolutePath: text }`), with every other import
 * resolved from disk. Tests pass their fixtures this way; the live path passes
 * the two contract files and leaves their imports to the real tree.
 */
function programFor(sources, options = compilerOptions()) {
  const host = ts.createCompilerHost(options, /* setParentNodes */ true);
  const readSourceFile = host.getSourceFile.bind(host);
  const fileExists = host.fileExists.bind(host);
  const directoryExists = host.directoryExists?.bind(host);
  const readFile = host.readFile.bind(host);
  const directories = new Set(
    Object.keys(sources).map((fileName) => resolve(fileName, "..")),
  );

  host.getSourceFile = (fileName, languageVersion, onError, shouldCreate) => {
    if (!Object.hasOwn(sources, fileName))
      return readSourceFile(fileName, languageVersion, onError, shouldCreate);
    return ts.createSourceFile(
      fileName,
      sources[fileName],
      languageVersion,
      /* setParentNodes */ true,
    );
  };
  host.fileExists = (fileName) =>
    Object.hasOwn(sources, fileName) || fileExists(fileName);
  // Relative imports between in-memory files resolve only when their directory
  // is visible to the resolver as well.
  host.directoryExists = (directory) =>
    directories.has(directory) || Boolean(directoryExists?.(directory));
  host.readFile = (fileName) =>
    Object.hasOwn(sources, fileName) ? sources[fileName] : readFile(fileName);

  return ts.createProgram({
    rootNames: Object.keys(sources),
    options,
    host,
  });
}

/** The interface declaration named `name`, or an error naming the file. */
function findInterface(source, name, file) {
  let found;
  source.forEachChild((node) => {
    if (ts.isInterfaceDeclaration(node) && node.name.text === name) found = node;
  });
  if (!found)
    throw new Error(
      `${relative(ROOT, file)} no longer declares \`interface ${name}\` — ` +
        "the contract gate cannot read it",
    );
  return found;
}

/**
 * Whether a declaration belongs to this checkout rather than to a library.
 * `node_modules` holds React's `ComponentType`, the TypeScript lib and every
 * other package's types: their shape is not this repository's to promise, so
 * they are recorded by name. Everything declared here is expanded.
 */
function isOwnSource(file) {
  return Boolean(file) && !file.includes("/node_modules/");
}

/**
 * The wire schema a generated type names, or `undefined` for a type declared
 * by hand. `api-generated.ts` is the backend's published schema, frozen by
 * `make check-api-types` and the backend's DTO snapshot; recording its shape
 * again would put a copy of the wire contract in this file, and every backend
 * field would churn it. The module contract records which schema a prop
 * carries, so re-pointing a frontend alias at another schema still fails.
 */
function generatedSchemaOf(context, type) {
  const symbols = [type.aliasSymbol, type.getSymbol()].filter(Boolean);
  const generated = symbols.some((symbol) =>
    (symbol.declarations ?? []).some(
      (declaration) =>
        declaration.getSourceFile().fileName === GENERATED_TYPES_PATH,
    ),
  );
  if (!generated) return undefined;

  return schemaNames(context).get(type) ?? "?";
}

const schemaNameCache = new WeakMap();

/** `Type -> schema name` for everything under `components["schemas"]`. */
function schemaNames(context) {
  const cached = schemaNameCache.get(context.program);
  if (cached) return cached;
  const names = new Map();
  schemaNameCache.set(context.program, names);

  const source = context.program.getSourceFile(GENERATED_TYPES_PATH);
  if (!source) return names;
  let components;
  source.forEachChild((node) => {
    if (ts.isInterfaceDeclaration(node) && node.name.text === "components")
      components = node;
  });
  const schemas = components?.members.find(
    (member) => member.name?.getText() === "schemas",
  );
  if (!schemas?.type) return names;
  const { checker } = context;
  for (const property of checker.getPropertiesOfType(
    checker.getTypeFromTypeNode(schemas.type),
  )) {
    const declaration = property.valueDeclaration ?? property.declarations?.[0];
    if (!declaration) continue;
    names.set(
      checker.getTypeOfSymbolAtLocation(property, declaration),
      property.getName(),
    );
  }
  return names;
}

/** A named type's name, unless the checker made one up for an object literal. */
function typeName(type) {
  const symbol = type.aliasSymbol ?? type.getSymbol();
  const name = symbol?.getName();
  if (!name || name.startsWith("__")) return undefined;
  return name;
}

function declarationFile(type) {
  const symbol = type.aliasSymbol ?? type.getSymbol();
  return symbol?.declarations?.[0]?.getSourceFile()?.fileName;
}

/** Sort object keys so the snapshot's diff carries only real changes. */
function sortKeys(value) {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value && typeof value === "object") {
    const sorted = {};
    for (const key of Object.keys(value).sort()) sorted[key] = sortKeys(value[key]);
    return sorted;
  }
  return value;
}

/** A descriptor's canonical text, for equality regardless of key order. */
function canonical(descriptor) {
  return JSON.stringify(sortKeys(descriptor));
}

/**
 * A type as a JSON descriptor. Strings are the primitive keywords; objects are
 * shaped `{ obj }` (named fields), `{ index }` (index signatures), `{ array }`,
 * `{ tuple }`, `{ union }`, `{ intersect }`, `{ fn }`, `{ ext }` (a type
 * declared outside this checkout, kept by name and arguments), `{ schema }`
 * (a wire schema from `api-generated.ts`, kept by name), `{ literal }`,
 * `{ ref }` (a cycle, kept by name) or `{ param }`.
 */
function describeType({ program, checker }, type, stack = []) {
  const context = { program, checker };
  if (stack.includes(type)) return { ref: typeName(type) ?? "<recursive>" };
  const next = [...stack, type];
  const flags = type.flags;

  if (flags & ts.TypeFlags.String) return "string";
  if (flags & ts.TypeFlags.Number) return "number";
  if (flags & ts.TypeFlags.Boolean) return "boolean";
  if (flags & ts.TypeFlags.Any) return "any";
  if (flags & ts.TypeFlags.Unknown) return "unknown";
  if (flags & ts.TypeFlags.Never) return "never";
  if (flags & ts.TypeFlags.Void) return "void";
  if (flags & ts.TypeFlags.Null) return "null";
  if (flags & ts.TypeFlags.Undefined) return "undefined";
  if (flags & ts.TypeFlags.StringLiteral) return { literal: type.value };
  if (flags & ts.TypeFlags.NumberLiteral) return { literal: type.value };

  // `Array<T>` and `T[]` are the same contract written two ways, so both are
  // recorded as an array of the element before any name is looked at.
  if (checker.isArrayType(type))
    return { array: describeType(context, checker.getTypeArguments(type)[0], next) };
  if (checker.isTupleType(type))
    return {
      tuple: checker
        .getTypeArguments(type)
        .map((member) => describeType(context, member, next)),
    };

  const name = typeName(type);
  if (name && !isOwnSource(declarationFile(type))) {
    // Type arguments are recorded only when the library type is generic and
    // the arguments are the contract's own (`Record<string, string>`,
    // `ComponentType<…>`). An alias such as `LucideIcon` is declared with its
    // React plumbing already filled in; that is the package's business, not
    // this contract's, and recording it would churn on a dependency upgrade.
    const symbol = type.aliasSymbol ?? type.getSymbol();
    const declaration = symbol?.declarations?.[0];
    const generic =
      !declaration || (declaration.typeParameters?.length ?? 0) > 0;
    const args = generic
      ? (type.aliasTypeArguments ?? type.typeArguments ?? [])
      : [];
    return args.length === 0
      ? { ext: name }
      : { ext: name, args: args.map((arg) => describeType(context, arg, next)) };
  }

  const schema = generatedSchemaOf(context, type);
  if (schema) return { schema };

  if (type.isTypeParameter())
    return { param: type.getSymbol()?.getName() ?? "?" };

  if (flags & ts.TypeFlags.Union) {
    const members = [];
    let sawTrue = false;
    let sawFalse = false;
    for (const member of type.types) {
      if (member.flags & ts.TypeFlags.BooleanLiteral) {
        if (member.intrinsicName === "true") sawTrue = true;
        else sawFalse = true;
        continue;
      }
      members.push(describeType(context, member, next));
    }
    // A checker splits `boolean` into `true | false`; the contract reads one
    // keyword, so the pair is put back together.
    if (sawTrue && sawFalse) members.push("boolean");
    members.sort((a, b) => canonical(a).localeCompare(canonical(b)));
    return members.length === 1 ? members[0] : { union: members };
  }

  if (flags & ts.TypeFlags.Intersection)
    return {
      intersect: type.types.map((member) => describeType(context, member, next)),
    };

  const signature = type.getCallSignatures()[0];
  if (signature) {
    const fn = {};
    fn.params = signature.getParameters().map((parameter) => {
      const declaration =
        parameter.valueDeclaration ?? parameter.declarations?.[0];
      const optional =
        Boolean(parameter.flags & ts.SymbolFlags.Optional) ||
        (ts.isParameter(declaration) &&
          Boolean(declaration.questionToken || declaration.initializer));
      const parameterType = declaration
        ? checker.getTypeOfSymbolAtLocation(parameter, declaration)
        : undefined;
      return {
        name: parameter.getName(),
        optional,
        type: parameterType
          ? describeType(context, parameterType, next)
          : "unknown",
      };
    });
    fn.returns = describeType(context, signature.getReturnType(), next);
    return { fn };
  }

  const props = {};
  for (const property of type.getProperties()) {
    const declaration =
      property.valueDeclaration ??
      property.declarations?.[0] ??
      type.aliasSymbol?.declarations?.[0] ??
      type.getSymbol()?.declarations?.[0];
    const propertyType = declaration
      ? checker.getTypeOfSymbolAtLocation(property, declaration)
      : undefined;
    props[property.getName()] = {
      optional: Boolean(property.flags & ts.SymbolFlags.Optional),
      type: propertyType
        ? describeType(context, propertyType, next)
        : "unknown",
    };
  }
  const indexes = checker.getIndexInfosOfType(type).map((info) => ({
    key: describeType(context, info.keyType, next),
    value: describeType(context, info.type, next),
  }));

  if (Object.keys(props).length > 0 || indexes.length === 0) return { obj: props };
  return { index: indexes };
}

function memberContract(context, declaration, where) {
  const props = {};
  for (const member of declaration.members) {
    if (!ts.isPropertySignature(member) || !ts.isIdentifier(member.name))
      throw new Error(
        `${where} carries a member this gate cannot read (${member.getText()}); ` +
          "the module contract must stay a plain object type",
      );
    props[member.name.text] = {
      optional: Boolean(member.questionToken),
      type: describeType(
        context,
        context.checker.getTypeFromTypeNode(member.type),
      ),
    };
  }
  return { props };
}

/** `FrontendModule` or `SlotContribution` as `{ props: { name: shape } }`. */
function interfaceContract(context, name, file) {
  const source = context.program.getSourceFile(file);
  if (!source) throw new Error(`cannot read ${relative(ROOT, file)}`);
  const declaration = findInterface(source, name, file);
  return memberContract(context, declaration, `interface ${name}`);
}

/** `SlotDataMap` as `{ props: { slot: <slot data shape> } }`. */
function slotMapContract(context, file) {
  const source = context.program.getSourceFile(file);
  if (!source) throw new Error(`cannot read ${relative(ROOT, file)}`);
  const declaration = findInterface(source, "SlotDataMap", file);
  const slots = {};
  for (const member of declaration.members) {
    if (!ts.isPropertySignature(member) || !ts.isIdentifier(member.name))
      throw new Error(
        `SlotDataMap carries a member this gate cannot read ` +
          `(${member.getText()}); every slot must be a named property`,
      );
    if (!member.type)
      throw new Error(`slot \`${member.name.text}\` declares no type`);
    slots[member.name.text] = describeType(
      context,
      context.checker.getTypeFromTypeNode(member.type),
    );
  }
  return { props: slots };
}

function contractOf(program, interfacesPath, slotsPath) {
  const context = { program, checker: program.getTypeChecker() };
  return {
    version: SNAPSHOT_VERSION,
    frontendModule: interfaceContract(context, "FrontendModule", interfacesPath),
    slotContribution: interfaceContract(
      context,
      "SlotContribution",
      interfacesPath,
    ),
    slotDataMap: slotMapContract(context, slotsPath),
  };
}

/**
 * The contract of in-memory sources, for tests: `sources` is
 * `{ absolutePath: text }`, and every import one source does not carry is
 * resolved from disk.
 */
export function contractFromSources(sources, interfacesPath, slotsPath) {
  return contractOf(programFor(sources), interfacesPath, slotsPath);
}

/** The live contract, read from the two source files beside this script. */
export function readContract() {
  return contractOf(
    programFor({
      [INTERFACES_PATH]: readFileSync(INTERFACES_PATH, "utf8"),
      [SLOTS_PATH]: readFileSync(SLOTS_PATH, "utf8"),
    }),
    INTERFACES_PATH,
    SLOTS_PATH,
  );
}

/** A descriptor's kind, which decides how two of them are compared. */
function kindOf(descriptor) {
  if (typeof descriptor === "string") return "primitive";
  if (descriptor.obj) return "object";
  if (descriptor.index) return "index";
  if (descriptor.array) return "array";
  if (descriptor.tuple) return "tuple";
  if (descriptor.union) return "union";
  if (descriptor.intersect) return "intersect";
  if (descriptor.fn) return "function";
  if (descriptor.ext) return "external";
  if (descriptor.literal !== undefined) return "literal";
  if (descriptor.schema) return "schema";
  if (descriptor.ref) return "ref";
  if (descriptor.param) return "param";
  return "unknown";
}

/** A descriptor as a short phrase, for a one-line finding. */
function print(descriptor) {
  if (typeof descriptor === "string") return descriptor;
  switch (kindOf(descriptor)) {
    case "object":
      return "{ … }";
    case "index":
      return descriptor.index
        .map((entry) => `[key: ${print(entry.key)}]: ${print(entry.value)}`)
        .join("; ");
    case "array":
      return `${print(descriptor.array)}[]`;
    case "tuple":
      return `[${descriptor.tuple.map(print).join(", ")}]`;
    case "union":
      return descriptor.union.map(print).join(" | ");
    case "intersect":
      return descriptor.intersect.map(print).join(" & ");
    case "function":
      return `(…) => ${print(descriptor.fn.returns)}`;
    case "external":
      return `${descriptor.ext}${
        descriptor.args ? "<…>" : ""
      }`;
    case "literal":
      return JSON.stringify(descriptor.literal);
    case "schema":
      return descriptor.schema;
    case "ref":
      return descriptor.ref;
    case "param":
      return descriptor.param;
    default:
      return JSON.stringify(descriptor);
  }
}

function typeChanged(where, before, after, changes) {
  changes.push(`${where}: type ${print(before)} -> ${print(after)}`);
}

/** A descriptor without the `undefined` an optional member carries. */
function withoutUndefined(descriptor) {
  if (!descriptor || !descriptor.union) return descriptor;
  const rest = descriptor.union.filter((member) => member !== "undefined");
  if (rest.length === 1) return rest[0];
  return { union: rest };
}

function compareMembers(where, before, after, changes) {
  for (const [name, shape] of Object.entries(before ?? {})) {
    const now = after?.[name];
    if (!now) {
      changes.push(`${where}.${name}: removed (or renamed)`);
      continue;
    }
    if (shape.optional && !now.optional) {
      changes.push(`${where}.${name}: optional -> required`);
      // Making a member required drops the `| undefined` from its type; only
      // a change beyond that is a second finding.
      compareType(
        `${where}.${name}`,
        withoutUndefined(shape.type),
        now.type,
        changes,
      );
      continue;
    }
    compareType(`${where}.${name}`, shape.type, now.type, changes);
  }
  for (const [name, shape] of Object.entries(after ?? {})) {
    if (before?.[name]) continue;
    if (!shape.optional)
      changes.push(
        `${where}.${name}: new required field (only optional fields may be added)`,
      );
  }
}

function compareObjects(where, before, after, changes) {
  compareMembers(where, before.obj, after.obj, changes);
  const beforeIndex = before.index ?? [];
  const afterIndex = after.index ?? [];
  for (let i = 0; i < beforeIndex.length; i++) {
    const now = afterIndex[i];
    if (!now) {
      changes.push(`${where}: index signature ${print(beforeIndex[i])} removed`);
      continue;
    }
    compareType(
      `${where}[key: ${print(now.key)}]`,
      beforeIndex[i].value,
      now.value,
      changes,
    );
    if (canonical(beforeIndex[i].key) !== canonical(now.key))
      typeChanged(`${where}: index key`, beforeIndex[i].key, now.key, changes);
  }
}

function compareFunction(where, before, after, changes) {
  const beforeParams = before.fn.params;
  const afterParams = after.fn.params;
  for (let i = 0; i < beforeParams.length; i++) {
    const was = beforeParams[i];
    const now = afterParams[i];
    if (!now) {
      changes.push(`${where}(${was.name}): parameter removed`);
      continue;
    }
    if (was.optional && !now.optional)
      changes.push(`${where}(${now.name}): optional -> required`);
    compareType(`${where}(${now.name})`, was.type, now.type, changes);
  }
  for (let i = beforeParams.length; i < afterParams.length; i++) {
    if (!afterParams[i].optional)
      changes.push(
        `${where}(${afterParams[i].name}): new required parameter ` +
          "(only optional parameters may be added)",
      );
  }
  compareType(`${where}(): return`, before.fn.returns, after.fn.returns, changes);
}

/** A union's members; a type not written as a union is a union of one. */
function unionMembers(descriptor) {
  return kindOf(descriptor) === "union" ? descriptor.union : [descriptor];
}

const NULLABLE_MEMBERS = new Set(["undefined", "null"]);

/**
 * Two unions as the sets of values a module may meet. A member added is
 * additive; a member removed is a finding. When both carry one payload member
 * and the same nullable members, the payloads are compared field by field so a
 * nested change names its field instead of reporting the whole member.
 */
function compareUnion(where, before, after, changes) {
  const beforeNullable = before.filter((member) => NULLABLE_MEMBERS.has(member));
  const afterNullable = after.filter((member) => NULLABLE_MEMBERS.has(member));
  const beforePayload = before.filter((member) => !NULLABLE_MEMBERS.has(member));
  const afterPayload = after.filter((member) => !NULLABLE_MEMBERS.has(member));

  if (
    beforePayload.length === 1 &&
    afterPayload.length === 1 &&
    canonical(beforeNullable) === canonical(afterNullable)
  ) {
    compareType(where, beforePayload[0], afterPayload[0], changes);
    return;
  }

  const afterMembers = new Set(after.map(canonical));
  for (const member of before) {
    if (!afterMembers.has(canonical(member)))
      changes.push(`${where}: union member ${print(member)} removed`);
  }
}

/**
 * Compare two descriptors, recording whatever a module built against `before`
 * would break on. Additions are not changes: an optional field, an extra union
 * member and an optional parameter all leave an existing module compiling.
 *
 * A union — and a type not written as one, which is a union of one — is
 * compared as a set of values, so a required member becoming optional
 * (`string` -> `string | undefined`) and an added member pass while a member
 * that disappeared is a finding. `undefined` and `null` are distinct members:
 * a module testing for one does not see the other.
 */
function compareType(where, before, after, changes) {
  if (canonical(before) === canonical(after)) return;

  if (kindOf(before) === "union" || kindOf(after) === "union") {
    compareUnion(where, unionMembers(before), unionMembers(after), changes);
    return;
  }

  const kind = kindOf(before);
  if (kind !== kindOf(after)) {
    typeChanged(where, before, after, changes);
    return;
  }

  switch (kind) {
    case "object":
      compareObjects(where, before, after, changes);
      return;
    case "index":
      compareObjects(
        where,
        { obj: {}, index: before.index },
        { obj: {}, index: after.index },
        changes,
      );
      return;
    case "array":
      compareType(`${where}[]`, before.array, after.array, changes);
      return;
    case "tuple": {
      for (let i = 0; i < before.tuple.length; i++) {
        if (!after.tuple[i]) {
          changes.push(`${where}[${i}]: removed from the tuple`);
          continue;
        }
        compareType(`${where}[${i}]`, before.tuple[i], after.tuple[i], changes);
      }
      return;
    }
    case "intersect": {
      const afterMembers = new Set(after.intersect.map(canonical));
      for (const member of before.intersect) {
        if (!afterMembers.has(canonical(member)))
          changes.push(`${where}: intersect member ${print(member)} removed`);
      }
      return;
    }
    case "function":
      compareFunction(where, before, after, changes);
      return;
    case "external": {
      if (before.ext !== after.ext) {
        typeChanged(where, before, after, changes);
        return;
      }
      const beforeArgs = before.args ?? [];
      const afterArgs = after.args ?? [];
      for (let i = 0; i < Math.max(beforeArgs.length, afterArgs.length); i++) {
        if (!beforeArgs[i] || !afterArgs[i]) {
          changes.push(`${where}: type ${print(before)} -> ${print(after)}`);
          return;
        }
        compareType(`${where}<arg ${i}>`, beforeArgs[i], afterArgs[i], changes);
      }
      return;
    }
    default:
      typeChanged(where, before, after, changes);
  }
}

/**
 * Breaking changes between two recorded contracts. Additions are not changes:
 * a module ignores a name it does not use, and a slot contributor ignores data
 * it does not read.
 */
export function breakingChanges(previous, current) {
  const changes = [];

  compareMembers(
    "frontendModule",
    previous.frontendModule?.props,
    current.frontendModule?.props,
    changes,
  );
  compareMembers(
    "slotContribution",
    previous.slotContribution?.props,
    current.slotContribution?.props,
    changes,
  );

  const before = previous.slotDataMap?.props ?? {};
  const now = current.slotDataMap?.props ?? {};
  for (const [slot, shape] of Object.entries(before)) {
    if (!now[slot]) {
      changes.push(`slotDataMap.${slot}: slot removed (or renamed)`);
      continue;
    }
    compareType(`slotDataMap.${slot}`, shape, now[slot], changes);
  }

  return changes;
}

/** The props a slot passes, for the guide check: an object slot's fields. */
function slotProps(shape) {
  return shape?.obj ?? {};
}

/**
 * The guide's slot table as `[{ slot, props: [name], optional: [name], status }]`,
 * `optional` holding the props the row writes as `name?`. The section
 * ends at the status-semantics note; a table that no longer sits between the
 * two is an error rather than an empty answer.
 */
export function readGuideTable(markdown) {
  const start = markdown.indexOf(GUIDE_HEADING);
  if (start === -1)
    throw new Error(`no "${GUIDE_HEADING}" in the module guide`);
  const end = markdown.indexOf(GUIDE_NEXT_HEADING, start);
  const section = markdown.slice(start, end === -1 ? undefined : end);

  const rows = [];
  for (const line of section.split("\n")) {
    if (!line.trimStart().startsWith("|")) continue;
    const cells = line
      .trim()
      .replace(/^\||\|$/g, "")
      .split("|")
      .map((cell) => cell.trim());
    if (cells.length < 4) continue;
    const slot = cells[0].match(/^`([a-z_]+)`$/);
    if (!slot) continue; // header and separator rows

    const props = [];
    const optional = [];
    for (const token of cells[2].matchAll(/`([^`]+)`/g)) {
      // A call's parameters (`onReject(request, notes?)`) are not props.
      const text = token[1].replace(/^\{|\}$/g, "").replace(/\(.*$/, "");
      for (const part of text.split(",")) {
        const written = part.trim();
        const name = written.replace(/\?$/, "");
        if (!name || !/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) continue;
        props.push(name);
        if (written.endsWith("?")) optional.push(name);
      }
    }
    rows.push({ slot: slot[1], props, optional, status: cells[3] });
  }
  return rows;
}

/** Slot names an in-tree module registers into today. */
export function contributedSlots(dir = MODULES_PATH) {
  const contributed = new Set();
  const walk = (directory) => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const full = resolve(directory, entry.name);
      if (entry.isDirectory()) {
        walk(full);
        continue;
      }
      if (!/\.(ts|tsx)$/.test(entry.name) || /\.test\.tsx?$/.test(entry.name))
        continue;
      const text = readFileSync(full, "utf8");
      for (const match of text.matchAll(/slot:\s*"([a-z_]+)"/g))
        contributed.add(match[1]);
    }
  };
  if (existsSync(dir)) walk(dir);
  return contributed;
}

/**
 * Findings where the guide and the map disagree: a slot the map does not
 * carry, a slot with no row, a prop the slot does not pass, a prop the slot
 * passes and the row leaves out, a prop marked optional the other way round,
 * or a status that no longer describes the tree.
 */
export function guideFindings(slots, rows, contributed) {
  const findings = [];
  const byName = new Map();

  for (const row of rows) {
    if (byName.has(row.slot)) findings.push(`GUIDE DUPLICATE  ${row.slot}`);
    byName.set(row.slot, row);
  }

  for (const [slot, row] of byName) {
    const shape = slots[slot];
    if (!shape) {
      findings.push(`GUIDE UNKNOWN SLOT  ${slot} — not in SlotDataMap`);
      continue;
    }
    const passed = slotProps(shape);
    for (const prop of row.props) {
      if (!Object.hasOwn(passed, prop))
        findings.push(
          `GUIDE UNKNOWN PROP  ${slot}.${prop} — the slot does not pass it`,
        );
    }
    for (const [prop, field] of Object.entries(passed)) {
      if (!row.props.includes(prop)) {
        findings.push(
          `GUIDE MISSING PROP  ${slot}.${prop} — the slot passes it, the row does not list it`,
        );
        continue;
      }
      const saysOptional = row.optional.includes(prop);
      if (saysOptional !== Boolean(field.optional))
        findings.push(
          `GUIDE OPTIONAL  ${slot}.${prop} — the row says ` +
            `${saysOptional ? "optional" : "required"}, the type says ` +
            `${field.optional ? "optional" : "required"}`,
        );
    }
    const active = contributed.has(slot);
    const saysActive = row.status.startsWith("Active");
    if (active !== saysActive)
      findings.push(
        `GUIDE STATUS  ${slot} — table says "${row.status}", ` +
          (active
            ? "an in-tree module contributes to it"
            : "no in-tree module contributes to it"),
      );
  }

  for (const slot of Object.keys(slots)) {
    if (!byName.has(slot)) findings.push(`GUIDE MISSING  ${slot}`);
  }

  return findings;
}

function plural(count, one, many) {
  return `${count} ${count === 1 ? one : many}`;
}

function main() {
  const args = process.argv.slice(2);
  const guideOnly = args.includes("--guide");

  if (!guideOnly) {
    const current = readContract();

    if (args.includes("--write-snapshot")) {
      writeFileSync(
        SNAPSHOT_PATH,
        `${JSON.stringify(sortKeys(current), null, 2)}\n`,
      );
      console.log(
        `✓ module contract snapshot refreshed: ` +
          `${Object.keys(current.slotDataMap.props).length} slot(s)`,
      );
      process.exit(0);
    }

    if (!existsSync(SNAPSHOT_PATH)) {
      console.error(
        `✗ no module contract snapshot at ${relative(ROOT, SNAPSHOT_PATH)} — ` +
          "run: npm run check:modules:contract:write",
      );
      process.exit(1);
    }

    const previous = JSON.parse(readFileSync(SNAPSHOT_PATH, "utf8"));
    if (previous.version !== SNAPSHOT_VERSION) {
      console.error(
        `✗ module contract snapshot version ${previous.version} — this gate ` +
          `reads version ${SNAPSHOT_VERSION}; regenerate it`,
      );
      process.exit(1);
    }

    const changes = breakingChanges(previous, current);
    if (changes.length > 0) {
      for (const change of changes) console.error(`MODULE-CONTRACT ${change}`);
      console.error(
        "\n✗ the module contract changed in a way an external module cannot " +
          "follow. A rename leaves the old name registered; a new optional " +
          "field, a new slot and an optional parameter are additive and pass. " +
          "If the break is intended, regenerate " +
          "(npm run check:modules:contract:write) and say why in the commit " +
          "message; after v0.11.0 it also gets a **Breaking** entry in " +
          "CHANGELOG.md (AGENTS.md, Changelog).",
      );
      process.exit(1);
    }

    console.log(
      `module-contract: ${plural(
        Object.keys(current.slotDataMap.props).length,
        "slot",
        "slots",
      )}, ` +
        `${plural(
          Object.keys(current.frontendModule.props).length,
          "FrontendModule field",
          "FrontendModule fields",
        )}, snapshot matches`,
    );
  }

  if (!existsSync(GUIDE_PATH)) {
    console.log(
      `module-contract: guide not mounted at ${relative(
        ROOT,
        GUIDE_PATH,
      )} — slot table not checked here`,
    );
    return;
  }

  const slots = readContract().slotDataMap.props;
  const guide = readFileSync(GUIDE_PATH, "utf8");
  const findings = guideFindings(slots, readGuideTable(guide), contributedSlots());

  if (findings.length > 0) {
    for (const finding of findings) console.error(`MODULE-CONTRACT ${finding}`);
    console.error(
      "\n✗ the guide's slot table disagrees with SlotDataMap. Add a row for a " +
        "new slot (the other columns are prose: where it renders and what it is " +
        "for), remove a slot that is gone, list every prop the slot passes " +
        "(`name?` for an optional one), and correct any status the tree no " +
        "longer supports.",
    );
    process.exit(1);
  }

  console.log(
    `module-contract: guide lists ${plural(
      Object.keys(slots).length,
      "slot",
      "slots",
    )}, table matches`,
  );
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === resolve(new URL(import.meta.url).pathname)
) {
  main();
}
