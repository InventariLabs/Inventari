/**
 * dnd-kit speaks the reader's language, answers the keyboard, and names
 * things the way the element names itself — and every drag context in the
 * tree borrows all of that from one place.
 *
 * Three halves. The first is behaviour: the hook answers with the hidden
 * keyboard instructions and the live-region announcements in the language
 * the reader picked — the words dnd-kit would otherwise supply in English
 * defaults. The second is the keyboard: the instruction promises "press the
 * space bar, move with the arrows", and that promise is kept only where the
 * context's sensors include the KeyboardSensor — which every context takes
 * from the shared `useDndSensors` hook, so the hook itself is pinned here.
 * The third is wiring: none of the overrides work where a DndContext fails
 * to spread them, so every source file in the tree that owns a DndContext
 * is read here and must call the hooks and spread the object — the file
 * list is not written down anywhere, it is discovered by reading the tree,
 * so a brand-new context in a brand-new file joins this gate the moment it
 * exists. Removing a spread, dropping the KeyboardSensor, or adding an
 * unwired context to a file that already has one all fail this test, and
 * each of those failures is what keeps the rule true when the next drag
 * context is written. The sortable flag of that hook is read as a value and
 * not as the shape of the call — the literal a call writes, or what the
 * variable it names holds — so a screen that hides `true` behind a `const`
 * is judged like the one that spells it, and a flag the rule cannot read is
 * a failure rather than the shrug that let one such screen through.
 *
 * The fourth is the split: the a11y attributes and the drag listeners land
 * on one node, unless the listening node is itself registered with
 * `setActivatorNodeRef` — and the registration is read on that element, in
 * the surface's own function, so a handle registered elsewhere in the file
 * forgives nothing. The fifth is the name: every surface that hands a `data`
 * object to dnd-kit must put the reader's word for the element in it under
 * DND_LABEL — a surface with no data at all keeps the shared fallback to its
 * id, which the hook's own tests pin above.
 */
import { describe, expect, it } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import ts from "typescript";

// withLanguage puts English back itself, inside act, while the hook is still
// mounted. A bare changeLanguage in an afterEach here would re-render the
// hook outside act: vitest runs "after" hooks in reverse order, so it comes
// before RTL's cleanup in the shared setup.
import { withLanguage } from "@/test/mocks/i18n";

import { useDndA11y } from "./dndA11y";

describe("useDndA11y", () => {
  it("describes keyboard dragging in the reader's language", async () => {
    const { result } = renderHook(() => useDndA11y());
    expect(result.current.screenReaderInstructions.draggable).toMatch(
      /press the space bar/,
    );

    await withLanguage("pl", async () => {
      expect(result.current.screenReaderInstructions.draggable).toContain(
        "naciśnij spację",
      );
    });
  });

  it("announces pickup, moves, drops and cancellation in that language", async () => {
    const { result } = renderHook(() => useDndA11y());
    const active = { id: "tile-3" };
    const over = { id: "cell-9" };

    expect(
      result.current.announcements.onDragStart?.({ active } as never),
    ).toBe("Picked up draggable element tile-3.");
    expect(
      result.current.announcements.onDragEnd?.({ active, over } as never),
    ).toBe("Draggable element tile-3 was dropped over droppable area cell-9");
    expect(
      result.current.announcements.onDragOver?.({
        active,
        over: null,
      } as never),
    ).toBe("Draggable element tile-3 is no longer over a droppable area.");

    await withLanguage("pl", async () => {
      act(() => {});
      expect(
        result.current.announcements.onDragStart?.({ active } as never),
      ).toBe("Podniesiono element tile-3.");
      expect(
        result.current.announcements.onDragCancel?.({ active } as never),
      ).toBe("Przeciąganie anulowano. Element tile-3 został upuszczony.");
    });
  });

  it("announces the element's own name when it carries one, and the id only when it does not", async () => {
    const { result } = renderHook(() => useDndA11y());
    // The name a draggable hands over in its data is the one the reader
    // hears — the screen shows the recipe, the announcement says the recipe.
    const named = {
      id: "recipe-card:7f3a",
      data: { current: { dndLabel: "Tiramisu" } },
    };
    const namedOver = {
      id: "collection:9b1e",
      data: { current: { dndLabel: "Desery" } },
    };

    expect(
      result.current.announcements.onDragStart?.({ active: named } as never),
    ).toBe("Picked up draggable element Tiramisu.");
    expect(
      result.current.announcements.onDragEnd?.({
        active: named,
        over: namedOver,
      } as never),
    ).toBe("Draggable element Tiramisu was dropped over droppable area Desery");

    // An element with no human name does not fall silent — the machine id is
    // a poor name, but it is the only one there is (the fallback is recorded
    // on DND_LABEL in dndA11y.ts). A blank label counts as none.
    const blank = {
      id: "entry-1",
      data: { current: { dndLabel: "   " } },
    };
    expect(
      result.current.announcements.onDragStart?.({ active: blank } as never),
    ).toBe("Picked up draggable element entry-1.");
  });
});

describe("every drag context in the tree takes its words and its keyboard from the shared hooks", () => {
  // A context is wired when its file calls the shared hook and spreads the
  // object on it. Both `accessibility={dndA11y}` and a legal extension of
  // the object — `accessibility={{ ...dndA11y, restoreFocus: false }}` —
  // count as spreading; a line commented out counts as neither a context
  // nor a spread. The literal map this test once compared against is gone
  // on purpose: a second, unwired context in a file the test already knew
  // used to slip through green.
  const CONTEXT = /<DndContext\b/g;
  const WIRED = /accessibility=\{\s*(?:\{\s*)?(?:\.\.\.\s*)?dndA11y\b/g;

  function sourceFiles(dir: string): string[] {
    const out: string[] = [];
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry);
      if (statSync(full).isDirectory()) {
        if (entry === "node_modules" || entry === "__tests__") continue;
        out.push(...sourceFiles(full));
      } else if (/\.(tsx?|jsx?)$/.test(entry) && !/\.test\.tsx?$/.test(entry)) {
        out.push(full);
      }
    }
    return out;
  }

  /** Line comments are not code: a commented-out spread wires nothing. */
  function withoutLineComments(text: string): string {
    return text
      .split("\n")
      .filter((line) => !/^\s*\/\//.test(line))
      .join("\n")
      .replace(/\/\*[\s\S]*?\*\//g, " ");
  }

  it("the shared sensor hook keeps the keyboard among the sensors", () => {
    const hookText = readFileSync(resolve(__dirname, "./dndA11y.ts"), "utf8");
    // The import alone wires nothing: the keyboard counts only when it is
    // handed to useSensor, so an unused word in the import block is not a
    // sensor.
    expect(
      hookText,
      "the keyboard must stay a sensor of the shared hook",
    ).toMatch(/useSensor\(\s*KeyboardSensor\b/);
    expect(
      hookText,
      "sortable contexts reorder with the keyboard in sibling steps",
    ).toMatch(
      /coordinateGetter:\s*sortable\s*\?\s*sortableKeyboardCoordinates/,
    );
  });

  it("each file owning a DndContext spreads the overrides and starts from the shared sensors", () => {
    const src = resolve(__dirname, "..");
    const owners = sourceFiles(src).filter((file) => {
      const text = withoutLineComments(readFileSync(file, "utf8"));
      return (text.match(CONTEXT)?.length ?? 0) > 0;
    });
    // The gate means nothing if it reads an empty tree — drag contexts
    // exist in this app, and if discovery suddenly finds none, the walk
    // broke.
    expect(
      owners.length,
      "drag contexts were expected in the tree",
    ).toBeGreaterThan(0);

    for (const file of owners) {
      const text = withoutLineComments(readFileSync(file, "utf8"));
      const contexts = text.match(CONTEXT)?.length ?? 0;
      const relative = file.replace(src + "/", "src/");
      expect(text, `${relative} must call the shared a11y hook`).toContain(
        "useDndA11y()",
      );
      expect(text, `${relative} must start from the shared sensors`).toContain(
        "useDndSensors(",
      );
      expect(
        text.match(WIRED)?.length ?? 0,
        `${relative} must pass the overrides to each of its ${contexts} DndContext(s)`,
      ).toBe(contexts);
      expect(text, `${relative} must not keep library defaults`).not.toContain(
        "defaultScreenReaderInstructions",
      );
    }
  });

  /**
   * The `const` bindings of the file, by name — the values the rule looks
   * through when a call hands it a variable instead of a literal. Only
   * `const` holds a value the source fixes: a `let` is a slot somebody may
   * have written to since, so it stays unreadable. A name declared twice
   * keeps both initialisers, and the rule reads a value only where they
   * agree — two components binding one name differently must not become a
   * guess.
   */
  function declaredBindings(
    source: ts.SourceFile,
  ): Map<string, ts.Expression[]> {
    const bindings = new Map<string, ts.Expression[]>();
    const collect = (node: ts.Node): void => {
      if (
        ts.isVariableDeclaration(node) &&
        node.initializer &&
        ts.isIdentifier(node.name) &&
        ts.isVariableDeclarationList(node.parent) &&
        (node.parent.flags & ts.NodeFlags.Const) !== 0
      ) {
        const values = bindings.get(node.name.text) ?? [];
        values.push(node.initializer);
        bindings.set(node.name.text, values);
      }
      ts.forEachChild(node, collect);
    };
    collect(source);
    return bindings;
  }

  /**
   * What the sortable flag comes to: `true`, `false`, or the value the
   * variable it names holds — through parentheses, `as`, and a non-null
   * assertion, which change nothing at runtime. `undefined` is "the rule
   * cannot read this": a computed expression, a property, a name bound to two
   * different values, a cycle. Unreadable is a finding, never a pass.
   */
  function sortableFlag(
    expression: ts.Expression,
    bindings: Map<string, ts.Expression[]>,
    seen: ReadonlySet<string> = new Set(),
  ): boolean | undefined {
    let node = expression;
    for (;;) {
      if (
        ts.isParenthesizedExpression(node) ||
        ts.isAsExpression(node) ||
        ts.isNonNullExpression(node)
      ) {
        node = node.expression;
        continue;
      }
      break;
    }
    if (node.kind === ts.SyntaxKind.TrueKeyword) return true;
    if (node.kind === ts.SyntaxKind.FalseKeyword) return false;
    const name = node;
    if (!ts.isIdentifier(name) || seen.has(name.text)) return undefined;
    const values = bindings.get(name.text);
    if (!values) return undefined;
    const resolved = new Set(
      values.map((value) =>
        sortableFlag(value, bindings, new Set([...seen, name.text])),
      ),
    );
    return resolved.size === 1 ? [...resolved][0] : undefined;
  }

  /**
   * What one file says about sortable keyboard steps: the flag every
   * `useDndSensors` call hands over (`true`, `false`, or `undefined` where the
   * rule cannot read it) and whether the file holds sortable machinery at all.
   * The file is parsed, not grepped: a comment or a string may name
   * `SortableContext` without meaning it, and an import specifier is a name
   * mentioned, not machinery held.
   */
  function readDragKeyboard(
    text: string,
    fileName: string,
  ): { flags: (boolean | undefined)[]; sorts: boolean } {
    const source = ts.createSourceFile(
      fileName,
      text,
      ts.ScriptTarget.Latest,
      true,
      fileName.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
    );
    const bindings = declaredBindings(source);
    const flags: (boolean | undefined)[] = [];
    let sorts = false;
    const read = (node: ts.Node): void => {
      if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) {
        return;
      }
      if (ts.isIdentifier(node)) {
        if (node.text === "useSortable" || node.text === "SortableContext") {
          sorts = true;
        } else if (
          node.text === "useDndSensors" &&
          ts.isCallExpression(node.parent) &&
          node.parent.expression === node
        ) {
          const flag = node.parent.arguments[1];
          flags.push(flag ? sortableFlag(flag, bindings) : undefined);
        }
      }
      ts.forEachChild(node, read);
    };
    read(source);
    return { flags, sorts };
  }

  it("reads the sortable flag through the variable that holds it", () => {
    // The case that exposed the gap: a screen with `useDndSensors(6, flag)`
    // and `const flag = true` carried exactly the defect the rule exists for
    // and passed, because the rule read the text of the call. These cases pin
    // the shapes it reads and the shapes it refuses — a value it cannot read
    // is a finding, never a pass.
    const file = (body: string): string =>
      `import { useDndSensors } from "@/lib/dndA11y";\n${body}\n`;
    const flags = (body: string): (boolean | undefined)[] =>
      readDragKeyboard(file(body), "probe.tsx").flags;

    expect(flags("const sensors = useDndSensors(6, true);")).toEqual([true]);
    expect(flags("const sensors = useDndSensors(6, false);")).toEqual([false]);
    expect(
      flags(
        "const keyboardSortable = true;\n" +
          "const sensors = useDndSensors(6, keyboardSortable);",
      ),
    ).toEqual([true]);
    // A variable that names another variable holds the value all the same.
    expect(
      flags(
        "const inner = true as const;\n" +
          "const outer = (inner);\n" +
          "const sensors = useDndSensors(6, outer);",
      ),
    ).toEqual([true]);
    // A `let` is a slot somebody may have written to since; a property and a
    // call answer values the rule does not follow.
    expect(
      flags(
        "let keyboardSortable = true;\n" +
          "const sensors = useDndSensors(6, keyboardSortable);",
      ),
    ).toEqual([undefined]);
    expect(flags("const sensors = useDndSensors(6, props.sortable);")).toEqual([
      undefined,
    ]);
    // One name, two values: the rule refuses to pick.
    expect(
      flags(
        "function A() {\n" +
          "  const keyboardSortable = true;\n" +
          "  return useDndSensors(6, keyboardSortable);\n" +
          "}\n" +
          "function B() {\n" +
          "  const keyboardSortable = false;\n" +
          "  return useDndSensors(6, keyboardSortable);\n" +
          "}",
      ),
    ).toEqual([undefined, undefined]);

    // Machinery is read from code: an import and a comment name it, a call
    // and a JSX tag hold it.
    expect(
      readDragKeyboard(
        'import { SortableContext } from "@dnd-kit/sortable";\n' +
          "// SortableContext is what the arrows resolve against\n" +
          "const sensors = useDndSensors(6, false);",
        "probe.tsx",
      ).sorts,
    ).toBe(false);
    expect(
      readDragKeyboard(
        "const sensors = useDndSensors(6, true);\n" +
          "const { setNodeRef } = useSortable({ id: 'tile' });",
        "probe.tsx",
      ).sorts,
    ).toBe(true);
  });

  it("asks for sortable keyboard steps exactly where the file sorts", () => {
    // sortableKeyboardCoordinates resolves the lifted element against the
    // containers registered in a SortableContext. Where nothing is sortable
    // the getter answers undefined: the space bar lifts the element, the
    // arrows never move it, and the instruction's promise is unkept. The rule
    // is therefore an equality, and it is read in both directions: a file
    // holding sortable machinery must ask for the sortable steps, and a file
    // without the machinery must not — a drag-into-target context keeps the
    // library's default coordinates.
    //
    // The flag is read as a value, not as the shape of the call. Reading the
    // text of the call let a screen that hides `true` behind a `const` pass
    // green while carrying exactly the defect this rule exists for, and a
    // value the rule cannot read is that same blindness wearing a different
    // coat, so it reddens instead of shrugging.
    const src = resolve(__dirname, "..");
    for (const file of sourceFiles(src)) {
      const text = readFileSync(file, "utf8");
      // A file that never names the hook or the machinery can hold neither.
      // This filter reads text; the judgement below reads the parse tree,
      // where comments and strings can name things but only code means them.
      if (!/useDndSensors|useSortable|SortableContext/.test(text)) continue;
      const relative = file.replace(src + "/", "src/");
      const { flags, sorts } = readDragKeyboard(text, relative);

      expect(
        flags.filter((flag) => flag === undefined).length,
        `${relative} hands useDndSensors a sortable flag the gate cannot read ` +
          "— write a literal, or a `const` declared in the same file, so the " +
          "gate can tell whether the keyboard steps sort. A value it cannot " +
          "read is the blindness this rule exists for",
      ).toBe(0);

      if (sorts && flags.length > 0) {
        expect(
          flags,
          `${relative} holds sortable machinery but never asks the keyboard ` +
            "for sortable steps — sortableKeyboardCoordinates is what " +
            "resolves the lifted element against its SortableContext, so " +
            "without it the arrows never reorder the item",
        ).toContain(true);
      } else {
        expect(
          flags,
          `${relative} asks the keyboard for sortable steps, but nothing in ` +
            "it is sortable — sortableKeyboardCoordinates resolves against a " +
            "SortableContext, so where nothing sorts the keyboard lifts the " +
            "element and never moves it",
        ).not.toContain(true);
      }
    }
  });

  /**
   * The third half of the class: the a11y attributes and the drag listeners
   * a draggable surface takes from `useDraggable`/`useSortable` have to land
   * on one node — unless the node that takes the listeners is handed over to
   * dnd-kit with `setActivatorNodeRef`, which is the library's own answer to
   * a separate handle. The naive rule "attributes and listeners sit on the
   * same JSX element" is wrong, because the split is legitimate exactly
   * there; the rule forgives the split only where the registered handle IS
   * the listening node — the registration is read on the element, not by the
   * name of the call, and the walk stays inside the surface's own function,
   * so a handled split in one component does not excuse a split in another.
   *
   * A surface that destructures one of the two names but spreads it nowhere
   * is the defect itself, half-applied: attributes without listeners name an
   * element a reader can never lift, and listeners without attributes lift a
   * thing the reader was never told about.
   *
   * A spread is counted through whatever expression carries it, so the
   * conditional form `{...(drag ? { ...attributes, ...listeners } : {})}`
   * spreads both onto its element no less than a bare `{...attributes}`.
   * Aliased destructuring (`{ attributes: dragAttributes }`) is read the way
   * the runtime reads it: by the local name.
   */
  interface DragSurface {
    attributeAliases: string[];
    listenerAliases: string[];
    activatorAlias: string | null;
    attributeElements: number[];
    listenerElements: number[];
    activatorElements: number[];
  }

  /** A split is forgiven only where the listening node is the handle itself. */
  function handledActivator(surface: DragSurface): boolean {
    return surface.listenerElements.some((element) =>
      surface.activatorElements.includes(element),
    );
  }

  /** The function-like node a declaration lives in; the file when top-level. */
  function surfaceScope(node: ts.Node): ts.Node {
    for (let current = node.parent; current; current = current.parent) {
      if (ts.isFunctionLike(current)) return current;
    }
    return node.getSourceFile();
  }

  /** Whether the node sits under the scope at all — nested callbacks count. */
  function withinScope(node: ts.Node, scope: ts.Node): boolean {
    for (
      let current: ts.Node | undefined = node;
      current;
      current = current.parent
    ) {
      if (current === scope) return true;
    }
    return false;
  }

  function readDragSurfaces(text: string, fileName: string): DragSurface[] {
    const source = ts.createSourceFile(
      fileName,
      text,
      ts.ScriptTarget.Latest,
      true,
      fileName.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
    );

    // Every JSX element registers an index, the names its spread attributes
    // carry, and the ref it hands over.
    const elementNames = new Map<number, Set<string>>();
    const elementRefs = new Map<number, string>();
    const elementNodes = new Map<number, ts.Node>();
    // A registration call names the ref object whose element is the handle:
    // `setActivatorNodeRef(handleRef.current)` → `handleRef`.
    const activatorCallHandles = new Map<string, Set<string>>();
    const namesIn = (node: ts.Node, into: Set<string>): void => {
      if (ts.isIdentifier(node)) into.add(node.text);
      ts.forEachChild(node, (child) => namesIn(child, into));
    };
    const collectElements = (node: ts.Node): void => {
      if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
        const index = elementNames.size;
        const names = new Set<string>();
        for (const attribute of node.attributes.properties) {
          if (ts.isJsxSpreadAttribute(attribute)) {
            namesIn(attribute.expression, names);
          }
          // dnd-kit takes the activator registration as a ref callback:
          // `ref={setActivatorNodeRef}` hands the function itself over, so
          // the reference — not a call — is the registration.
          if (
            ts.isJsxAttribute(attribute) &&
            attribute.name.getText() === "ref" &&
            attribute.initializer &&
            ts.isJsxExpression(attribute.initializer) &&
            attribute.initializer.expression &&
            ts.isIdentifier(attribute.initializer.expression)
          ) {
            elementRefs.set(index, attribute.initializer.expression.text);
          }
        }
        elementNames.set(index, names);
        elementNodes.set(index, node);
      }
      ts.forEachChild(node, collectElements);
    };
    collectElements(source);

    // Some surfaces register from an effect instead: `setActivatorNodeRef(
    // handleRef.current)` is a call, and the element with `ref={handleRef}`
    // is the handle it registers.
    const collectCalls = (node: ts.Node): void => {
      if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)) {
        const argument = node.arguments[0];
        if (
          argument &&
          ts.isPropertyAccessExpression(argument) &&
          argument.name.text === "current" &&
          ts.isIdentifier(argument.expression)
        ) {
          const handles =
            activatorCallHandles.get(node.expression.text) ?? new Set<string>();
          handles.add(argument.expression.text);
          activatorCallHandles.set(node.expression.text, handles);
        }
      }
      ts.forEachChild(node, collectCalls);
    };
    collectCalls(source);

    const collectSites = (node: ts.Node): void => {
      if (
        ts.isVariableDeclaration(node) &&
        ts.isObjectBindingPattern(node.name) &&
        node.initializer &&
        ts.isCallExpression(node.initializer) &&
        ts.isIdentifier(node.initializer.expression) &&
        ["useDraggable", "useSortable"].includes(
          node.initializer.expression.text,
        )
      ) {
        const surface: DragSurface = {
          attributeAliases: [],
          listenerAliases: [],
          activatorAlias: null,
          attributeElements: [],
          listenerElements: [],
          activatorElements: [],
        };
        for (const element of node.name.elements) {
          if (!ts.isBindingElement(element)) continue;
          const local = element.name.getText();
          const property =
            element.propertyName && ts.isIdentifier(element.propertyName)
              ? element.propertyName.text
              : local;
          if (property === "attributes") surface.attributeAliases.push(local);
          else if (property === "listeners")
            surface.listenerAliases.push(local);
          else if (property === "setActivatorNodeRef")
            surface.activatorAlias = local;
        }
        // The surface's elements are the ones in its own function: a sibling
        // component's element that happens to spread the same alias names
        // belongs to the sibling, not here.
        const scope = surfaceScope(node);
        for (const [index, names] of elementNames) {
          const elementNode = elementNodes.get(index);
          if (!elementNode || !withinScope(elementNode, scope)) continue;
          if (surface.attributeAliases.some((alias) => names.has(alias)))
            surface.attributeElements.push(index);
          if (surface.listenerAliases.some((alias) => names.has(alias)))
            surface.listenerElements.push(index);
          const ref = elementRefs.get(index);
          if (ref === undefined || surface.activatorAlias === null) continue;
          // Direct: the registered handle is the ref itself. Effect: the
          // handle is the ref object the registration call was handed.
          if (
            ref === surface.activatorAlias ||
            activatorCallHandles.get(surface.activatorAlias)?.has(ref)
          ) {
            surface.activatorElements.push(index);
          }
        }
        sites.push(surface);
      }
      ts.forEachChild(node, collectSites);
    };
    const sites: DragSurface[] = [];
    collectSites(source);
    return sites;
  }

  it("every draggable surface keeps its a11y attributes and its drag listeners on one node, or registers a handle", () => {
    const src = resolve(__dirname, "..");
    let surfaces = 0;
    for (const file of sourceFiles(src)) {
      const text = withoutLineComments(readFileSync(file, "utf8"));
      // A file that never names the draggable hooks holds no surface; the
      // droppables and the contexts answer to the rules above.
      if (!/useDraggable|useSortable/.test(text)) continue;
      const relative = file.replace(src + "/", "src/");
      for (const surface of readDragSurfaces(text, relative)) {
        if (
          surface.attributeAliases.length === 0 &&
          surface.listenerAliases.length === 0
        )
          continue;
        surfaces += 1;
        const shared = surface.attributeElements.filter((element) =>
          surface.listenerElements.includes(element),
        );
        const split =
          surface.attributeElements.length > 0 &&
          surface.listenerElements.length > 0 &&
          shared.length === 0;
        if (split && !handledActivator(surface)) {
          expect(
            shared.length,
            `${relative} spreads the a11y attributes and the drag listeners ` +
              "on different elements and no setActivatorNodeRef registers the " +
              "listening element as the handle — the reader is told about one " +
              "element and lifts another. Put both on one element, or register " +
              "the listening element with setActivatorNodeRef, which is the " +
              "library's own answer to a separate handle",
          ).toBeGreaterThan(0);
        }
        if (
          surface.attributeAliases.length > 0 &&
          surface.attributeElements.length === 0
        ) {
          expect(
            surface.attributeElements.length,
            `${relative} destructures the a11y attributes and spreads them ` +
              "nowhere — the reader is never told the element is draggable. " +
              "Spread them on the draggable element, or leave them out of " +
              "the destructure",
          ).toBeGreaterThan(0);
        }
        if (
          surface.listenerAliases.length > 0 &&
          surface.listenerElements.length === 0
        ) {
          expect(
            surface.listenerElements.length,
            `${relative} destructures the drag listeners and spreads them ` +
              "nowhere — nothing in it can be lifted. Spread them on the " +
              "element meant to start the drag, or leave them out of the " +
              "destructure",
          ).toBeGreaterThan(0);
        }
      }
    }
    // The rule means nothing over an empty tree: the app drags recipes onto
    // a meal planner, and if discovery suddenly finds no surface, the walk
    // broke.
    expect(
      surfaces,
      "draggable surfaces were expected in the tree",
    ).toBeGreaterThanOrEqual(3);
  });

  it("reads the shapes a surface is written in, and refuses the split without a handle", () => {
    const surfacesOf = (body: string): DragSurface[] =>
      readDragSurfaces(body, "probe.tsx");
    const splitOf = (surface: DragSurface): number =>
      surface.attributeElements.filter((element) =>
        surface.listenerElements.includes(element),
      ).length;

    // The Launcher shape: both spread on the element that carries the ref.
    const same = surfacesOf(
      'import { useSortable } from "@dnd-kit/sortable";\n' +
        "const { attributes, listeners, setNodeRef } = useSortable({ id: 'x' });\n" +
        "const view = <li ref={setNodeRef} {...attributes} {...listeners} />;",
    );
    expect(same).toHaveLength(1);
    expect(splitOf(same[0])).toBe(1);

    // The RecipeCard shape: a conditional spread still puts both names on
    // its element.
    const conditional = surfacesOf(
      'import { useSortable } from "@dnd-kit/sortable";\n' +
        "const { attributes, listeners, setNodeRef } = useSortable({ id: 'x' });\n" +
        "const view = (\n" +
        "  <a ref={setNodeRef} {...(drag ? { ...attributes, ...listeners } : {})} />\n" +
        ");",
    );
    expect(splitOf(conditional[0])).toBe(1);

    // The defect the rule exists for: the attributes on the outer element,
    // the listeners on an inner one, and no registration anywhere.
    const split = surfacesOf(
      'import { useSortable } from "@dnd-kit/sortable";\n' +
        "const { attributes, listeners, setNodeRef } = useSortable({ id: 'x' });\n" +
        "const view = (\n" +
        "  <li ref={setNodeRef} {...attributes}>\n" +
        "    <a {...listeners}>open</a>\n" +
        "  </li>\n" +
        ");",
    );
    expect(splitOf(split[0])).toBe(0);
    expect(handledActivator(split[0])).toBe(false);

    // The legitimate split: the listening element is registered as the
    // activator, and the rule forgives exactly that.
    const handled = surfacesOf(
      'import { useSortable } from "@dnd-kit/sortable";\n' +
        "const { attributes, listeners, setNodeRef, setActivatorNodeRef } = useSortable({ id: 'x' });\n" +
        "const view = (\n" +
        "  <li ref={setNodeRef} {...attributes}>\n" +
        "    <button ref={setActivatorNodeRef} {...listeners}>drag</button>\n" +
        "  </li>\n" +
        ");",
    );
    expect(splitOf(handled[0])).toBe(0);
    expect(handledActivator(handled[0])).toBe(true);

    // A registration that lands on an element carrying no listeners: the
    // name is used, the node is wrong, and the split must stay red — the
    // reading is per element, not per name.
    const registeredElsewhere = surfacesOf(
      'import { useSortable } from "@dnd-kit/sortable";\n' +
        "const { attributes, listeners, setNodeRef, setActivatorNodeRef } = useSortable({ id: 'x' });\n" +
        "const view = (\n" +
        "  <li ref={setNodeRef} {...attributes}>\n" +
        "    <a {...listeners}>open</a>\n" +
        "    <span ref={setActivatorNodeRef}>handle</span>\n" +
        "  </li>\n" +
        ");",
    );
    expect(splitOf(registeredElsewhere[0])).toBe(0);
    expect(handledActivator(registeredElsewhere[0])).toBe(false);

    // The effect shape registers the ref object the element hands over:
    // `setActivatorNodeRef(handleRef.current)` plus `ref={handleRef}` on the
    // listening node is the same legitimate split.
    const effectHandled = surfacesOf(
      'import { useSortable } from "@dnd-kit/sortable";\n' +
        "const { attributes, listeners, setNodeRef, setActivatorNodeRef } = useSortable({ id: 'x' });\n" +
        "const handleRef = { current: null };\n" +
        "setActivatorNodeRef(handleRef.current);\n" +
        "const view = (\n" +
        "  <li ref={setNodeRef} {...attributes}>\n" +
        "    <button ref={handleRef} {...listeners}>drag</button>\n" +
        "  </li>\n" +
        ");",
    );
    expect(splitOf(effectHandled[0])).toBe(0);
    expect(handledActivator(effectHandled[0])).toBe(true);

    // One handled split in a file does not forgive another surface's split:
    // attribution stays inside each surface's own function.
    const twoComponents = surfacesOf(
      'import { useSortable } from "@dnd-kit/sortable";\n' +
        "function Handled() {\n" +
        "  const { attributes, listeners, setNodeRef, setActivatorNodeRef } = useSortable({ id: 'a' });\n" +
        "  return (\n" +
        "    <li ref={setNodeRef} {...attributes}>\n" +
        "      <button ref={setActivatorNodeRef} {...listeners}>drag</button>\n" +
        "    </li>\n" +
        "  );\n" +
        "}\n" +
        "function Broken() {\n" +
        "  const { attributes, listeners, setNodeRef, setActivatorNodeRef } = useSortable({ id: 'b' });\n" +
        "  return (\n" +
        "    <li ref={setNodeRef} {...attributes}>\n" +
        "      <a {...listeners}>open</a>\n" +
        "    </li>\n" +
        "  );\n" +
        "}",
    );
    expect(twoComponents).toHaveLength(2);
    expect(
      twoComponents.filter((surface) => handledActivator(surface)),
    ).toHaveLength(1);
    const broken = twoComponents.filter(
      (surface) => !handledActivator(surface),
    );
    expect(broken).toHaveLength(1);
    expect(splitOf(broken[0])).toBe(0);

    // An alias is read by the local name, the way the runtime reads it.
    const aliased = surfacesOf(
      'import { useSortable } from "@dnd-kit/sortable";\n' +
        "const { attributes: dragAttributes, listeners: dragListeners, setNodeRef } = useSortable({ id: 'x' });\n" +
        "const view = <li ref={setNodeRef} {...dragAttributes} {...dragListeners} />;",
    );
    expect(splitOf(aliased[0])).toBe(1);

    // Half-applied: a name destructured and spread nowhere is a finding, not
    // a pass.
    const half = surfacesOf(
      'import { useSortable } from "@dnd-kit/sortable";\n' +
        "const { attributes, setNodeRef } = useSortable({ id: 'x' });\n" +
        "const view = <li ref={setNodeRef} {...attributes} />;",
    );
    expect(half[0].listenerElements).toHaveLength(0);
  });

  /**
   * The fifth half: the name a surface hands over. Every call that passes a
   * `data` object must carry the reader's word for the element under the
   * shared key — without it the announcement falls back to the machine id
   * (`recipe-card:acdf8675-…`) — the regression this rule exists for. A call
   * with no `data` at all is legal and keeps that fallback: an element that
   * was never given a human name is not a regression, and the hook's own
   * tests above pin what the reader hears then. The gate reads literals: a
   * `data` it cannot read is a finding, never a shrug.
   */
  const LABELLED_SURFACES = [
    "src/modules/launcher/components/Launcher.tsx",
    "src/modules/recipes/components/CollectionsPanel.tsx",
    "src/modules/recipes/components/MealPlanCell.tsx",
    "src/modules/recipes/components/MealPlanEntryCard.tsx",
    "src/modules/recipes/components/RecipeCard.tsx",
  ] as const;

  interface DragLabelRead {
    findings: string[];
    carrying: number;
  }

  function readDragLabels(text: string, fileName: string): DragLabelRead {
    const source = ts.createSourceFile(
      fileName,
      text,
      ts.ScriptTarget.Latest,
      true,
      fileName.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
    );
    // The key as the file spells it: the shared constant, or an alias of it.
    const labelNames = new Set<string>(["DND_LABEL", "dndLabel"]);
    for (const statement of source.statements) {
      if (!ts.isImportDeclaration(statement)) continue;
      const bindings = statement.importClause?.namedBindings;
      if (!bindings || !ts.isNamedImports(bindings)) continue;
      for (const element of bindings.elements) {
        if ((element.propertyName ?? element.name).text === "DND_LABEL") {
          labelNames.add(element.name.text);
        }
      }
    }

    const propertyName = (
      property: ts.PropertyAssignment | ts.ShorthandPropertyAssignment,
    ): string | null => {
      const name = property.name;
      if (ts.isIdentifier(name) || ts.isStringLiteral(name)) return name.text;
      return null;
    };

    const findings: string[] = [];
    let carrying = 0;
    const visit = (node: ts.Node): void => {
      if (
        ts.isCallExpression(node) &&
        ts.isIdentifier(node.expression) &&
        ["useDraggable", "useSortable", "useDroppable"].includes(
          node.expression.text,
        )
      ) {
        const config = node.arguments[0];
        if (!config || !ts.isObjectLiteralExpression(config)) {
          findings.push(
            `${fileName}: the ${node.expression.text} config is not a literal — ` +
              "the gate cannot read whether the element names itself. Write " +
              "the config, and the data in it, as object literals",
          );
        } else {
          let data:
            ts.PropertyAssignment | ts.ShorthandPropertyAssignment | null =
            null;
          for (const property of config.properties) {
            if (
              (ts.isPropertyAssignment(property) ||
                ts.isShorthandPropertyAssignment(property)) &&
              propertyName(property) === "data"
            ) {
              data = property;
            }
          }
          if (data !== null) {
            carrying += 1;
            const named =
              ts.isPropertyAssignment(data) &&
              ts.isObjectLiteralExpression(data.initializer) &&
              data.initializer.properties.some(
                (property) =>
                  (ts.isPropertyAssignment(property) ||
                    ts.isShorthandPropertyAssignment(property)) &&
                  (ts.isComputedPropertyName(property.name)
                    ? (ts.isIdentifier(property.name.expression) &&
                        labelNames.has(property.name.expression.text)) ||
                      (ts.isStringLiteral(property.name.expression) &&
                        property.name.expression.text === "dndLabel")
                    : propertyName(property) === "dndLabel"),
              );
            if (!named) {
              findings.push(
                `${fileName}: ${node.expression.text} hands the announcement ` +
                  "a data object without [DND_LABEL] — the reader hears the " +
                  "machine id instead of the name on screen. Put the visible " +
                  "name in data under DND_LABEL",
              );
            }
          }
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(source);
    return { findings, carrying };
  }

  it("every draggable and droppable that carries data names the element for the announcement", () => {
    const src = resolve(__dirname, "..");
    const findings: string[] = [];
    let carrying = 0;
    const carryingByFile = new Map<string, number>();
    for (const file of sourceFiles(src)) {
      const text = withoutLineComments(readFileSync(file, "utf8"));
      // A file that never names the drag hooks holds no surface to name.
      if (!/useDraggable|useSortable|useDroppable/.test(text)) continue;
      const relative = file.replace(src + "/", "src/");
      const read = readDragLabels(text, relative);
      findings.push(...read.findings);
      carrying += read.carrying;
      carryingByFile.set(relative, read.carrying);
    }
    expect(
      findings,
      "data-carrying drag surfaces must name themselves under DND_LABEL",
    ).toEqual([]);
    // The rule means nothing over an empty tree: the app drags recipes and
    // module tiles, and if discovery suddenly finds no data, the walk broke.
    expect(
      carrying,
      "drag surfaces carrying data were expected in the tree",
    ).toBeGreaterThan(0);
    // A surface whose data holds nothing but the label is the one case the
    // rule cannot see go: deleting the whole `data` property leaves a call
    // with no data, which is legal, and the announcement quietly goes back
    // to the machine id. These surfaces were written to carry the label, so
    // each one has to keep carrying data.
    for (const surface of LABELLED_SURFACES) {
      expect(
        carryingByFile.get(surface) ?? 0,
        `${surface} must keep handing its drag data, with the label, to dnd-kit`,
      ).toBeGreaterThan(0);
    }
  });

  it("reads label wiring as it is written, and refuses a nameless data object", () => {
    const findingsOf = (body: string): string[] =>
      readDragLabels(
        'import { useDraggable, useDroppable, useSortable } from "@dnd-kit/core";\n' +
          'import { DND_LABEL } from "@/lib/dndA11y";\n' +
          body,
        "probe.tsx",
      ).findings;

    // A surface that was never given a human name keeps the shared fallback:
    // no data is legal. (The hook's own tests pin what the reader hears.)
    expect(findingsOf("const a = useDraggable({ id: 'x' });")).toEqual([]);
    // The name under the shared key is the wiring the rule wants...
    expect(
      findingsOf(
        "const b = useDraggable({ id: 'x', data: { [DND_LABEL]: name } });",
      ),
    ).toEqual([]);
    expect(
      findingsOf(
        'const c = useDroppable({ id: "x", data: { "dndLabel": label } });',
      ),
    ).toEqual([]);
    // ...and a data object without it is that report in code.
    expect(
      findingsOf(
        "const d = useSortable({ id: 'x', data: { type: 'recipe' } });",
      ),
    ).toHaveLength(1);
    expect(
      findingsOf(
        "const e = useDroppable({ id: 'x', data: { type: 'cell' } });",
      ),
    ).toHaveLength(1);
    // A data the rule cannot read is a finding, never a pass.
    expect(
      findingsOf("const f = useDraggable({ id: 'x', data });"),
    ).toHaveLength(1);
    expect(findingsOf("const g = useDraggable(useDragConfig());")).toHaveLength(
      1,
    );
  });
});
