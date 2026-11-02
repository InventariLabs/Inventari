import { withoutComments } from "./lib.mjs";

/**
 * A module page that offers a write and never asks whether the account may.
 *
 * The backend refuses correctly — a translated 403, every time — so nothing
 * is ever written that should not be. What breaks is the moment: the reader
 * is shown the button, opens the form, fills it in, accepts the "this cannot
 * be undone" dialog, and is refused at the end of the work. On the documents
 * list that was five separate ways in, including a full correction form and a
 * bulk delete of forty-eight rows.
 *
 * It has now been found three times — the shell modules first (with
 * the `useCanWrite` hook written for them), equipment's template screen
 * second, documents third — and each time it was fixed page by page.
 * The class is the same every time: a page reaches for a mutation and nothing
 * anywhere in it names a permission.
 *
 * Deliberately narrow. It only looks at module *pages*, because a leaf
 * component is usually handed the answer as a prop by the page above it, and
 * it accepts any evidence that the question was asked at all — the hooks, the
 * notice, or a `canWrite`/`canManage` prop threaded in. Asking whether the
 * evidence guards the right control is a job for a reviewer; asking whether
 * anybody asked is a job a script can do, and it is the half that was skipped.
 *
 * It reads hooks as well as pages, because a page rarely calls a mutation
 * itself any more: it calls its module's hook and the hook calls
 * `useAppMutation`. The add-product form does exactly that, so the rule
 * counted it as writing nothing — and the one route into inventory that never
 * asked stayed invisible to a gate written to catch precisely that.
 *
 * It reads through the components a page renders, one hop at a time, because
 * the same blind spot appeared again one level down: the product card's page
 * calls no mutation itself — it renders a component that opens a modal that
 * mutates — and a page-only rule stayed green while a read-only account was
 * offered a fifteen-field form and refused on save. A page is bare
 * when nothing it renders, however deep, asks who is looking; a component
 * that asks for itself excuses the page, the same way a threaded `canWrite`
 * prop does.
 *
 * A walk of every no-permission cell in the app found the other half of that
 * boundary, so it is written down here rather than re-discovered: six screens
 * offered writes a read-only account was refused, and all six pass this rule.
 *
 * - A page that asks anywhere is excused whole, and the question and an
 *   ungated control sit in the same file, unrelated. The purchase-orders list
 *   gated its header action and left the empty state's CTA; the ingredient
 *   dictionary asked `useHasPermission` about reading nutrition labels while
 *   offering "Add override"; the production list carried the read-only notice
 *   with an active "New production" beside it. Whether the answer guards the
 *   right control is the reviewer's half, as above — and this is that half.
 * - A control that navigates to a screen that writes is a write only once the
 *   router is read. The label scan card's "Assign label" held no mutation; it
 *   opened the inventory scanner, whose own gate this rule does read. The
 *   exception is a route that opens the flow through its own fragment
 *   (`#receive`, `#pick`, `#execute`, `#edit`): the write is one navigation
 *   away and named in the URL, so `WRITE_FRAGMENT` counts it, and the notice
 *   alone will not excuse it (see `GATES`). The To do screen's Pick button was
 *   that shape while the rule called the page a reader.
 * - A write mounted by the slot registry arrives by name at render time, not
 *   as an `@/…` import, so the walk never reaches it: the product sheet's
 *   "Add to shopping list" and the overview's suggestions modal both sit
 *   behind `<Slot>`.
 *
 * The rule holds the half a script can ask — whether anybody asked at all.
 * These are where that half ends.
 */

/** A page that reaches for a mutation, however the module spells it. */
const WRITES =
  /\.mutateAsync\s*\(|\.mutate\s*\(|\buseMutation\s*[(<]|\buseAppMutation\s*[(<]/;

/**
 * A route whose fragment opens a floor flow rather than moving the reader.
 *
 * `useDocumentDetailHashOpen` turns four fragments into an open modal, and
 * every one of those modals writes: `#edit` saves a draft, while `#receive`,
 * `#pick` and `#execute` start a WMS session whose first request is a POST.
 * A page that navigates to one of them offers that write even though its own
 * file never calls a mutation — the To do screen's Pick button was exactly
 * this, and the rule counted the page as a reader.
 *
 * The fragment may be built (`#${type === "IN" ? "receive" : "pick"}`), which
 * is how the To do screen addresses its sessions, so the template form is
 * read too. Anchors to a section of a page (`#module-data`, `#pack`) are not
 * here: they move the reader, they start nothing.
 */
const WRITE_FRAGMENT =
  /#(?:edit|receive|pick|execute)\b|#\$\{[^}]*(?:edit|receive|pick|execute)\b/;

/**
 * The evidence that can keep a fragment navigation off the screen.
 *
 * `<ReadOnlyNotice>` is a caption: the To do screen carried it while every
 * row still offered Pick. A write the file only reaches by changing the URL
 * leaves the page no mutation of its own to ask beside, so the rule asks for
 * something that can gate a control — the hook, or a prop threaded from it —
 * rather than accepting the notice alone. Read as calls, so an import left
 * behind after the hook was removed is not evidence.
 */
const GATES =
  /useCan[A-Z]\w*\s*\(|useHasPermission\s*\(|\bcanWrite\b|\bcanManage\b/;

/** The names a file pulls in from anywhere — one entry per imported binding. */
const IMPORTED_NAMES = /import\s*(?:type\s+)?{([^}]*)}\s*from/g;

/**
 * The hooks that write, so a page calling one counts as writing.
 *
 * Read one export at a time, not one file at a time: a module keeps its reads
 * and its writes side by side — `useProductionOrders` next to
 * `useCreateProductionOrder` — and a rule that took the whole file would call
 * every page that merely lists production orders a writer.
 *
 * One level deep. A page calling a hook that calls a hook that mutates is out
 * of reach of a regex, and pretending otherwise would make the rule's own
 * answer unreadable. One level is where the class lives: a module keeps its
 * writes in `hooks/`, and the page calls them.
 */
function writingHooks(files) {
  const names = new Set();
  for (const file of files) {
    if (!/(^|\/)hooks\//.test(file.path)) continue;
    for (const piece of withoutComments(file.text).split(/\n\s*export\s/)) {
      const declared = /^(?:async\s+)?(?:function|const)\s+(use[A-Z]\w*)/.exec(
        piece,
      );
      if (declared && WRITES.test(piece)) names.add(declared[1]);
    }
  }
  return names;
}

/** Does this page call one of those hooks? */
function callsAWritingHook(text, hooks) {
  for (const [, bindings] of text.matchAll(IMPORTED_NAMES)) {
    for (const binding of bindings.split(",")) {
      const name = binding
        .trim()
        .split(/\s+as\s+/)[0]
        .trim();
      if (hooks.has(name) && new RegExp(`\\b${name}\\s*\\(`).test(text)) {
        return true;
      }
    }
  }
  return false;
}

/**
 * The local names a file takes from each `@/…` module it imports.
 *
 * Read as specifier plus binding, not as bare names like `callsAWritingHook`:
 * following a component means knowing *which file* the name stands for, and
 * the corpus is keyed by path. Value imports only — `import type` names never
 * render, and resolving them would only invite a false positive.
 */
const IMPORTS = /import\s+(type\s+)?([^"']+?)\s+from\s+"(@\/[^"]+)"/g;

function importsIn(text) {
  const out = [];
  for (const [, typeOnly, clause, specifier] of text.matchAll(IMPORTS)) {
    if (typeOnly) continue;
    const names = [];
    const named = /\{([^}]*)\}/.exec(clause);
    if (named) {
      for (const binding of named[1].split(",")) {
        const name = binding
          .trim()
          .split(/\s+as\s+/)
          .pop()
          .trim();
        if (name) names.push(name);
      }
    }
    const fallback = /^\s*([A-Za-z_$][\w$]*)\s*(?:,|$)/.exec(clause);
    if (fallback && !clause.trim().startsWith("{")) names.push(fallback[1]);
    if (names.length > 0) out.push({ specifier: specifier.slice(2), names });
  }
  return out;
}

/** The corpus file a `@/…` specifier names, if one exists. */
function resolveImport(byPath, specifier) {
  for (const candidate of [
    `${specifier}.tsx`,
    `${specifier}.ts`,
    `${specifier}/index.tsx`,
    `${specifier}/index.ts`,
  ]) {
    if (byPath.has(candidate)) return byPath.get(candidate);
  }
  return null;
}

/**
 * The component files this file renders.
 *
 * An import that is never written as a JSX tag is a helper or a type by
 * another name, not a surface on the page. Pages are skipped: one page
 * mounting another is not the shape this rule reads.
 */
function renderedFiles(file, byPath) {
  const text = withoutComments(file.text);
  const out = new Set();
  for (const { specifier, names } of importsIn(text)) {
    const target = resolveImport(byPath, specifier);
    if (!target) continue;
    if (/^modules\/[^/]+\/pages\//.test(target.path)) continue;
    if (names.some((name) => new RegExp(`<${name}(?=[\\s/>])`).test(text))) {
      out.add(target.path);
    }
  }
  return out;
}

/** Does this file reach for a mutation itself, or through one of its hooks? */
function writesItself(file, hooks) {
  const text = withoutComments(file.text);
  return (
    WRITES.test(text) ||
    WRITE_FRAGMENT.test(text) ||
    callsAWritingHook(text, hooks)
  );
}

/**
 * Is a write somewhere under this component, with nobody in the chain asking?
 *
 * Transitive, so the page that renders a panel that opens a mutating modal is
 * read the same as the page that mutates directly. A component that asks for
 * itself stops the walk: it is the one offering the control, and it holds the
 * answer.
 */
function ungatedWriteBelow(path, byPath, hooks, seen) {
  if (seen.has(path)) return false;
  seen.add(path);
  const file = byPath.get(path);
  if (!file) return false;
  if (writesItself(file, hooks)) {
    const text = withoutComments(file.text);
    // A fragment navigation is excused by a gate, not by the notice (see
    // `GATES`) — here as on the page, or the next instance one hop down
    // goes by unread.
    return WRITE_FRAGMENT.test(text) ? !GATES.test(text) : !ASKS.test(text);
  }
  for (const child of renderedFiles(file, byPath)) {
    if (ungatedWriteBelow(child, byPath, hooks, seen)) return true;
  }
  return false;
}

/** Is any write reachable under this component, asked about or not? */
function anyWriteBelow(path, byPath, hooks, seen) {
  if (seen.has(path)) return false;
  seen.add(path);
  const file = byPath.get(path);
  if (!file) return false;
  if (writesItself(file, hooks)) return true;
  for (const child of renderedFiles(file, byPath)) {
    if (anyWriteBelow(child, byPath, hooks, seen)) return true;
  }
  return false;
}

/**
 * Any sign that the page asked who is looking.
 *
 * `useCan…` covers the module hooks as well as the two shared ones: approvals
 * wraps its own key as `useCanConfigureWorkflows`, which is asking the
 * question by any reading, and a rule that only knew two spellings called
 * that page bare for as long as it existed.
 */
const ASKS =
  /useCan[A-Z]\w*|ReadOnlyNotice|useHasPermission|\bcanWrite\b|\bcanManage\b/;

/**
 * Pages that ask a question no permission set can answer yet.
 *
 * Both create the membership the permissions would be read from: the
 * onboarding page creates the organization, and joining by invitation is what
 * grants the account an organization at all. There is nothing to ask until
 * they run. A page whose component asks for itself no longer needs an entry —
 * the rule follows the render now — so the list holds only this shape.
 *
 * A page with no session at all is a different exemption and is not listed
 * here — see `publicPages` below.
 */
const EXEMPT = new Map([
  [
    // Runs before the account belongs anywhere: it is the screen that
    // creates the organization whose permissions every other page asks
    // about. There is nothing to ask yet.
    "modules/onboarding/pages/OnboardingPage.tsx",
    "creates the organization the permissions would be read from",
  ],
  [
    // Same shape: joining on an invitation code is what gives the account
    // an organization. Membership is the authorisation.
    "modules/settings/pages/JoinOrganizationPage.tsx",
    "joining is what grants the membership a permission would be read from",
  ],
]);

/**
 * The pages served without an account, read off the file that serves them.
 *
 * `PublicApp.tsx` says of itself "everything reachable without an account,
 * and nothing else", and `main.tsx` picks between it and `App` before either
 * is imported. A page mounted there has no session, so there is no account to
 * ask about and no permission to name — the confirmation link in an
 * attestation e-mail is the whole authorisation.
 *
 * Read rather than listed: adding a page to the public tree exempts it, and
 * moving it back out puts the rule back, with nothing to remember either way.
 */
function publicPages(files) {
  const app = files.find((file) => file.path === "PublicApp.tsx");
  if (!app) return new Set();

  return new Set(
    [...app.text.matchAll(/import\("@\/([^"]+)"\)/g)].map(
      (match) => `${match[1]}.tsx`,
    ),
  );
}

export default {
  name: "write-action-ungated",
  // Hooks are `.ts`; the pages' own corpus stops at `.tsx` and would hide
  // every write this rule now follows.
  corpus: "scripts",
  says:
    "A module page calls a mutation — or opens a write flow through a route " +
    "fragment — and never names a permission. The backend refuses correctly, " +
    "but only after the reader has done the work.",
  advice:
    '  const canWrite = useCanWrite("warehouse");\n' +
    "  …\n" +
    '  <ReadOnlyNotice module="warehouse" />\n' +
    "  {canWrite && <Button onClick={…}>Add</Button>}\n\n" +
    "`ReadOnlyNotice` renders nothing for an account that holds the right, so\n" +
    "it can sit unconditionally at the top of the page. Use `useCanManage`\n" +
    "for the settings a module guards with its own `:manage` key.",

  run(files) {
    const unauthenticated = publicPages(files);

    const hooks = writingHooks(files);
    const byPath = new Map(files.map((file) => [file.path, file]));

    const considered = files.filter((file) => {
      // A screen, not a helper beside one: routed pages are the files
      // directly in a module's `pages/` directory. The nested files there —
      // `ItemsPage/ItemsModalsContainer`, `StorageDetailPage/…Container` —
      // are rendered *by* the screen, which is where the question belongs.
      if (!/^modules\/[^/]+\/pages\/[^/]+\.tsx$/.test(file.path)) return false;
      if (EXEMPT.has(file.path) || unauthenticated.has(file.path)) return false;
      if (writesItself(file, hooks)) return true;
      return [...renderedFiles(file, byPath)].some((path) =>
        anyWriteBelow(path, byPath, hooks, new Set()),
      );
    });

    const findings = considered
      .filter((file) => {
        const text = withoutComments(file.text);
        // A fragment navigation is excused only by evidence that can gate a
        // control; the read-only notice beside it explains the screen.
        if (WRITE_FRAGMENT.test(text)) return !GATES.test(text);
        if (ASKS.test(text)) return false;
        if (writesItself(file, hooks)) return true;
        return [...renderedFiles(file, byPath)].some((path) =>
          ungatedWriteBelow(path, byPath, hooks, new Set()),
        );
      })
      .map((file) => file.path);

    return { considered: considered.length, findings };
  },
};
