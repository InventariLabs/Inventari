import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import jsxA11y from "eslint-plugin-jsx-a11y";
import globals from "globals";
import { readFileSync } from "node:fs";

// ─── Local rule: an unowned timer outlives everything ────────────────────
// A setTimeout/setInterval armed outside an effect keeps firing after its
// component is gone — and after a test environment is torn down, where
// `document` disappears exactly like `window`, so "touches only DOM" is NOT
// a safety reason (the third round of this bug class taught both halves).
// Outside an effect the timer must be owned: id held in a ref, cleared on
// unmount. The rule default-denies and `scripts/timer-exceptions.json`
// carries the deliberate sites, each with a reason.
const timerExceptions = JSON.parse(
  readFileSync(new URL("./scripts/timer-exceptions.json", import.meta.url), "utf8"),
);

const a11yBaselineFiles = Object.keys(
  JSON.parse(
    readFileSync(new URL("./scripts/a11y-baseline.json", import.meta.url), "utf8"),
  ).files,
);

const timersInEffects = {
  meta: {
    type: "problem",
    docs: {
      description:
        "setTimeout/setInterval outside an effect must be owned (id in a ref, cleared on unmount)",
    },
    schema: [
      {
        type: "object",
        properties: {
          allowed: {
            type: "object",
            additionalProperties: { type: "integer", minimum: 0 },
          },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      timerOutsideEffect:
        "{{fn}} is armed outside a useEffect/useLayoutEffect, so nobody owns it: it keeps firing after the component is gone — and after a test-environment teardown, where `document` vanishes exactly like `window` (touching only DOM is not a reason). Hold the id in a ref and clear it on unmount, move it into an effect, or — if the site is genuinely owned — add the file to scripts/timer-exceptions.json with the reason.",
      timerBeyondException:
        "{{fn}} is one unowned site more than this file's exception declares ({{allowed}}): the reason in scripts/timer-exceptions.json covers exactly {{allowed}} site(s), so this one is new — own it (id in a ref, cleared on unmount) or update the entry's `sites` with the reason extended.",
    },
  },
  create(context) {
    const allowed = context.options[0]?.allowed ?? {};
    const EFFECT_HOOKS = new Set(["useEffect", "useLayoutEffect"]);
    const TIMER_FNS = new Set(["setTimeout", "setInterval"]);

    const calleeName = (callee) => {
      if (callee.type === "Identifier") return callee.name;
      if (
        callee.type === "MemberExpression" &&
        !callee.computed &&
        callee.property.type === "Identifier"
      ) {
        return callee.property.name;
      }
      return null;
    };

    const insideEffect = (node) => {
      for (let cur = node.parent; cur; cur = cur.parent) {
        if (
          cur.type === "CallExpression" &&
          EFFECT_HOOKS.has(calleeName(cur.callee) ?? "")
        ) {
          return true;
        }
      }
      return false;
    };

    // Unowned sites are counted per file and judged at program exit: an
    // excepted file passes with exactly the number of sites its entry
    // declares, and every site beyond that number turns red — so a NEW timer
    // in a listed file is caught just like one in a fresh file.
    const unowned = [];
    const filename = context.filename ?? context.getFilename();
    const entry = Object.keys(allowed).find((p) => filename.endsWith(p));
    const declared = entry !== undefined ? allowed[entry] : 0;

    return {
      CallExpression(node) {
        const name = calleeName(node.callee);
        if (!name || !TIMER_FNS.has(name)) return;
        if (insideEffect(node)) return;
        unowned.push(node);
      },
      "Program:exit"() {
        for (const node of unowned.slice(declared)) {
          context.report({
            node,
            messageId: entry !== undefined ? "timerBeyondException" : "timerOutsideEffect",
            data: { fn: calleeName(node.callee), allowed: declared },
          });
        }
      },
    };
  },
};

export default tseslint.config(
  // ─── Global ignores (replaces .eslintignore) ───────────────────────────
  {
    ignores: [
      "node_modules/**",
      "coverage/**",
      "dist/**",
      "vite.config.ts",
      "frontend/**",
      // Root-level utility scripts (CommonJS/ESM, not part of the app).
      // scripts/ stays outside ESLint on purpose — these
      // are Node-run gates, and most carry their own vitest spec
      // (`*.test.mjs` beside them), so their correctness is enforced by
      // those specs, not by the app-oriented lint.
      "*.cjs",
      "*.mjs",
      "*.js",
      "scripts/**",
    ],
  },

  // ─── Base recommended configs (TS/TSX only) ────────────────────────────
  js.configs.recommended,
  ...tseslint.configs.recommended,

  // ─── Project config ────────────────────────────────────────────────────
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: {
        ...globals.browser,
      },
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
    plugins: {
      "react-hooks": reactHooks,
    },
    settings: {
      react: {
        version: "detect",
      },
    },
    rules: {
      // Keep hooks rules strict
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "error",
      // TypeScript tweaks
      "@typescript-eslint/no-unused-vars": "off",
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/ban-ts-comment": "off",
      "no-console": ["warn", { allow: ["error"] }],
      // Function-level size/complexity gates — files are split by
      // responsibility, not by a hard LOC limit (mirrors backend ruff
      // C901/PLR0915).
      // Thresholds calibrated 2026-08-09 so existing code needs no mass
      // grandfathering beyond the baseline overrides below; do not raise
      // them without a measurement pass.
      complexity: ["error", { max: 25 }],
      "max-lines-per-function": [
        "error",
        { max: 300, skipBlankLines: true, skipComments: true },
      ],

      // Architecture boundary: core components must not import from modules.
      // Modules inject UI via the Slot system instead.
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["**/modules/*"],
              importNamePattern: ".*",
              message:
                'Core components must not import from modules. Use <Slot name="..."> instead.',
            },
          ],
        },
      ],
    },
  },

  // ─── Baseline: grandfathered files for function-level metrics ──────────
  // Files that still hold a function over the limit. This list is the file
  // half of scripts/function-baseline.json: check-function-baseline.mjs
  // re-lints every file here with the limits switched back on and freezes
  // each function's number, so a frozen function may not grow, a new one in
  // a listed file is measured from its first line, and an entry that
  // silences nothing fails the run. Do not add a file by hand — nothing but
  // `--write-baseline` adds an entry, and it is the entry that shows in the
  // diff as debt.
  {
    name: "baseline:complexity-function-ratchet",
    files: [
      "src/modules/approvals/pages/ApprovalsDashboard.tsx",
      "src/modules/warehouse/components/DocumentActionButtons.tsx",
      "src/modules/warehouse/components/DocumentFormModal.tsx",
      "src/modules/warehouse/components/DocumentListItem.tsx",
      "src/modules/warehouse/components/DocumentMetadataGrid.tsx",
      "src/modules/warehouse/hooks/useDocumentScanner.ts",
      "src/modules/warehouse/hooks/useDocumentWorkspaceState.ts",
      "src/modules/warehouse/pages/DocumentDetailPage.tsx",
      "src/modules/equipment/pages/AssetListPage.tsx",
      "src/modules/inventory/hooks/useItemForm.ts",
      "src/modules/nutrition/components/FoodAndHealthExtra.tsx",
      "src/modules/partners/components/PartnerFormModal.tsx",
      "src/modules/recipes/components/PickingActivePhase.tsx",
      "src/modules/recipes/components/RecipeForm.tsx",
      "src/modules/shared/components/LineItemsEditor/LineItemRow.tsx",
      "src/modules/shared/components/LineItemsEditor/LineItemsEditor.tsx",
      "src/modules/shared/components/UomSelect.tsx",
      "src/modules/stats/pages/StatsPage.tsx",
      "src/modules/webhooks/components/WebhookForm.tsx",
    ],
    rules: {
      complexity: "off",
    },
  },

  // ─── Baseline: grandfathered files for max-lines-per-function (max 300)
  // Same file half of scripts/function-baseline.json as the block above.
  {
    name: "baseline:max-lines-per-function-ratchet",
    files: [
      "src/modules/warehouse/components/DocumentFormModal.tsx",
      "src/modules/warehouse/pages/DocumentDetailPage.tsx",
      "src/modules/equipment/components/ImportEquipmentModal.tsx",
      "src/modules/equipment/hooks/useAssetListActions.ts",
      "src/modules/equipment/pages/AssetListPage.tsx",
      "src/modules/inventory/pages/ItemsPage.tsx",
      "src/modules/maker/pages/ProductionDetailPage.tsx",
      "src/modules/inventory/pages/LabelPoolPage.tsx",
      "src/modules/recipes/components/PickingActivePhase.tsx",
      "src/modules/recipes/components/RecipeForm.tsx",
      "src/modules/recipes/pages/MealPlanDetailPage.tsx",
      "src/modules/recipes/pages/RecipesPage.tsx",
      "src/modules/recipes/pages/UnitConversionsPage.tsx",
    ],
    rules: {
      "max-lines-per-function": "off",
    },
  },

  // ─── Accessibility: jsx-a11y recommended rules on product markup ───────
  // Test files are left out on purpose: specs render stand-in components
  // whose markup is not what a user meets. The files that still carry a
  // finding are relaxed by the baseline block below, and
  // scripts/check-a11y-baseline.mjs freezes what each one still holds.
  {
    name: "a11y:jsx-a11y",
    files: ["src/**/*.tsx"],
    ignores: ["src/**/*.test.*", "src/test/**", "src/__mocks__/**"],
    plugins: { "jsx-a11y": jsxA11y },
    rules: jsxA11y.flatConfigs.recommended.rules,
  },

  // ─── Baseline: grandfathered files for jsx-a11y ────────────────────────
  // The files listed in scripts/a11y-baseline.json still hold a finding.
  // check-a11y-baseline.mjs lints the tree with this block dropped and
  // freezes each file's count per rule, so a frozen finding may not
  // multiply, a new one in a listed file is caught, and an entry that
  // silences nothing fails the run. Nothing but `--write-baseline` adds an
  // entry, and it is the entry that shows in the diff as debt.
  ...(a11yBaselineFiles.length
    ? [
        {
          name: "baseline:jsx-a11y-ratchet",
          files: a11yBaselineFiles,
          rules: Object.fromEntries(
            Object.keys(jsxA11y.flatConfigs.recommended.rules).map((rule) => [
              rule,
              "off",
            ]),
          ),
        },
      ]
    : []),

  // ─── Override: module files — imports from siblings allowed ────────────
  {
    files: ["src/modules/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": "off",
    },
  },

  // ─── Override: test files — relaxed rules ──────────────────────────────
  {
    files: [
      "src/test/**/*.{ts,tsx}",
      "**/*.test.{ts,tsx}",
      "**/*.spec.{ts,tsx}",
    ],
    rules: {
      "no-restricted-imports": "off",
      "@typescript-eslint/no-explicit-any": "warn",
      complexity: "off",
      "max-lines-per-function": "off",
    },
  },

  // ─── Override: E2E test infrastructure ─────────────────────────────────
  {
    files: ["tests/e2e/**/*.{ts,tsx}", "tests/**/*.{ts,tsx}"],
    languageOptions: {
      globals: {
        ...globals.node,
      },
    },
    rules: {
      "no-console": "off",
      "@typescript-eslint/no-explicit-any": "off",
      complexity: "off",
      "max-lines-per-function": "off",
      // E2E fixtures are not React components — hooks rule is a false positive
      "react-hooks/rules-of-hooks": "off",
      // Playwright test patterns assign values between steps for readability
      "no-useless-assignment": "off",
    },
  },

  // ─── Override: unit-test infrastructure ────────────────────────────────
  {
    // The console gate (src/test/consoleGate.ts) is the one place that takes
    // console.error and console.warn over on purpose, and the baseline writer
    // reports what it merged. Product code keeps the rule.
    files: ["src/test/**/*.{ts,tsx}"],
    languageOptions: {
      globals: {
        ...globals.node,
      },
    },
    rules: {
      "no-console": "off",
    },
  },

  // ─── Override: i18n config and the slot contract — module type info ────
  // Both are core files that describe module-owned data rather than import
  // module UI: the i18n config names module manifests, the slot map types
  // the payloads modules exchange through <Slot>. Type-only imports; no
  // module code runs here.
  {
    files: ["src/i18n/config.ts", "src/lib/moduleRegistry/slotProps.ts"],
    rules: {
      "no-restricted-imports": "off",
    },
  },

  // ─── Local rule: timers outside effects must be owned ──────────────────
  // Test files are excluded on purpose: specs arm timers deliberately under
  // fake timers, and the app-oriented lint does not judge them.
  {
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/**/*.test.*", "src/test/**", "src/__mocks__/**"],
    plugins: {
      "local-rules": { rules: { "timers-in-effects": timersInEffects } },
    },
    rules: {
      "local-rules/timers-in-effects": [
        "error",
        {
          allowed: Object.fromEntries(
            timerExceptions.exceptions.map((e) => [e.path, e.sites ?? 0]),
          ),
        },
      ],
    },
  },

  // ─── Override: mock files and test utilities ───────────────────────────
  {
    files: ["src/__mocks__/**/*.{ts,tsx}", "src/test/**/*.{ts,tsx}"],
    rules: {
      "@typescript-eslint/no-explicit-any": "warn",
    },
  },

  // ─── Override: App shell files (Layout, App) — module imports OK ───────
  {
    files: ["src/components/Layout.tsx", "src/App.tsx"],
    rules: {
      "no-restricted-imports": "off",
    },
  },

  // ─── Override: legacy hooks re-exports ─────────────────────────────────
  {
    files: ["src/hooks/**/*.{ts,tsx}", "src/hooks/useUoms.ts"],
    rules: {
      "no-restricted-imports": "off",
    },
  },

  // ─── Override: Shell header enforcement ──────────────────────────────
  // Module pages MUST use useModulePageHeader() instead of rendering their
  // own <h1> headings. Detail pages are exempt.
  {
    files: ["src/modules/**/*.tsx"],
    ignores: [
      "**/*.test.tsx",
      "**/*.spec.tsx",
      "**/onboarding/pages/OnboardingPage.tsx",
      "**/settings/pages/SettingsPage.tsx",
      "**/settings/components/AppStore.tsx",
      "**/spaces/components/StorageDetailHeader.tsx",
      "**/stock_takes/components/StockTakeHeader.tsx",
      "**/launcher/components/Launcher.tsx",
      "**/recipes/components/RecipePrintView.tsx",
    ],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "@/components/ui/PageContainer",
              message:
                'Module pages inside ModuleShell/SettingsShell must not use PageContainer — the shell owns padding. Return <div className="space-y-6"> instead.',
            },
          ],
        },
      ],
      "no-restricted-syntax": [
        "error",
        {
          selector: "JSXElement[openingElement.name.name='h1']",
          message:
            "FORBIDDEN: <h1> in module pages. Use useModulePageHeader() to let the Shell render the page title. Zero exceptions.",
        },
        {
          selector: "JSXElement[openingElement.name.name='button']",
          message:
            "Prefer <Button> from '@/components/ui/Button' over raw <button> for consistent styling, accessibility, and maintainability. If the use case requires custom sizing not covered by Button variants, add an eslint-disable comment with justification.",
        },
      ],
    },
  },

  // ─── Override: ListControlBar enforcement (pages/*.tsx) ──────────────
  {
    files: ["src/modules/**/pages/*.tsx"],
    ignores: [
      "**/*.test.tsx",
      "**/*.spec.tsx",
      "**/onboarding/pages/OnboardingPage.tsx",
      "**/settings/pages/SettingsPage.tsx",
    ],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector: "JSXElement[openingElement.name.name='h1']",
          message:
            "FORBIDDEN: <h1> in module pages. Use useModulePageHeader() to let the Shell render the page title. Zero exceptions.",
        },
        {
          selector: "JSXElement[openingElement.name.name='button']",
          message:
            "Prefer <Button> from '@/components/ui/Button' over raw <button> for consistent styling, accessibility, and maintainability. If the use case requires custom sizing not covered by Button variants, add an eslint-disable comment with justification.",
        },
        {
          selector:
            "JSXElement[openingElement.name.name='input'] > JSXOpeningElement:not(:has(JSXAttribute[name.name='type']))",
          message:
            'FORBIDDEN: raw <input> (no type) in page components. Use <Input> from \'@/components/ui/Input\' or <ListControlBar search={{...}}> instead.',
        },
        {
          selector:
            "JSXElement[openingElement.name.name='input'] > JSXOpeningElement > JSXAttribute[name.name='type'][value.value='text']",
          message:
            'FORBIDDEN: raw <input type="text"> in page components. Use <Input> from \'@/components/ui/Input\' or <ListControlBar search={{...}}> instead.',
        },
        {
          selector: "JSXElement[openingElement.name.name='select']",
          message:
            "FORBIDDEN: raw <select> in page components. Use <NativeSelect> from '@/components/ui/NativeSelect' for option-based selects, or <Select> for icon/color pickers, or <ListControlBar primaryTabs={{...}}> instead.",
        },
      ],
    },
  },

  // ─── Override: Design system <Button> for shell components ───────────
  {
    files: ["src/components/*.tsx"],
    ignores: ["**/*.test.tsx", "**/*.spec.tsx"],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector: "JSXElement[openingElement.name.name='button']",
          message:
            "Prefer <Button> from '@/components/ui/Button' over raw <button> for consistent styling, accessibility, and maintainability.",
        },
      ],
    },
  },
);
