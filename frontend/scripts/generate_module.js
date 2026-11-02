#!/usr/bin/env node
/**
 * Frontend module scaffold generator.
 * Usage: node scripts/generate_module.mjs <module_name>
 *
 * Auto-generates a fresh module under src/modules/<module_name>/ with all
 * boilerplate files: module.ts, pages/IndexPage.tsx, i18n/*.json and types.
 *   src/modules/{name}/
 *     module.ts
 *     pages/IndexPage.tsx
 *     components/  (empty, .gitkeep)
 *     hooks/       (empty, .gitkeep)
 *     i18n/en.json, pl.json, de.json, fr.json, es.json
 *     types/       (empty, .gitkeep - the quickstart's step 4 writes index.ts)
 */

import { existsSync, mkdirSync, writeFileSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
// MODULE_SCAFFOLD_ROOT lets the test generate into a temporary directory.
const srcRoot =
  process.env.MODULE_SCAFFOLD_ROOT ?? join(__dirname, "..", "src", "modules");

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

const name = process.argv[2];

if (!name) {
  console.error("Usage: node scripts/generate_module.mjs <module_name>");
  console.error("Example: node scripts/generate_module.mjs warranty_tracker");
  process.exit(1);
}

if (!/^[a-z][a-z0-9_]+$/.test(name)) {
  console.error(`Error: Invalid module name "${name}".`);
  console.error(
    "  Use lowercase letters, digits and underscores only (e.g. warranty_tracker).",
  );
  process.exit(1);
}

const moduleDir = join(srcRoot, name);

if (existsSync(moduleDir)) {
  console.error(
    `Error: Frontend module "${name}" already exists at ${moduleDir}`,
  );
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const pascal = name
  .split("_")
  .map((w) => w[0].toUpperCase() + w.slice(1))
  .join("");

const humanName = name
  .split("_")
  .map((w) => w[0].toUpperCase() + w.slice(1))
  .join(" ");

const routePath = "/" + name.replace(/_/g, "-");

function write(relPath, content) {
  const abs = join(moduleDir, relPath);
  mkdirSync(dirname(abs), { recursive: true });
  writeFileSync(abs, content, "utf8");
  console.log(`  created  src/modules/${name}/${relPath}`);
}

function touch(relPath) {
  const abs = join(moduleDir, relPath);
  mkdirSync(dirname(abs), { recursive: true });
  writeFileSync(abs, "", "utf8");
  console.log(`  created  src/modules/${name}/${relPath}`);
}

// ---------------------------------------------------------------------------
// Templates
// ---------------------------------------------------------------------------

const moduleTs = `import { lazy } from "react";
import { Package } from "lucide-react";
import { moduleRegistry } from "@/module-sdk";

const IndexPage = lazy(() => import("./pages/IndexPage"));

moduleRegistry.register({
  name: "${name}",
  routes: [
    {
      path: "${routePath}",
      component: IndexPage,
    },
  ],
  // The launcher lists only modules that declare a tile: without it the module
  // is switched on and then reachable only by its address.
  launcher: {
    displayName: "${name}:navigation.title",
    description: "${name}:description",
    icon: Package,
    category: "business",
  },
  moduleNav: {
    basePath: "${routePath}",
    items: [
      {
        path: "",
        icon: Package,
        labelKey: "${name}:navigation.title",
      },
    ],
  },
});
`;

// The shell renders a module page's title: the page hands it over through
// useModulePageHeader instead of drawing a heading of its own.
const indexPageTsx = `import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useModulePageHeader } from "@/module-sdk";

export default function IndexPage() {
  const { t } = useTranslation("${name}");
  const { setHeader } = useModulePageHeader();

  useEffect(() => {
    setHeader({ title: t("title"), subtitle: t("description") });
  }, [t, setHeader]);

  return <div className="space-y-6" />;
}
`;

function makeI18nJson(obj) {
  return JSON.stringify(obj, null, 2) + "\n";
}

const enObj = {
  title: humanName,
  description: `${humanName} module — add your description here.`,
  navigation: { title: humanName },
  permissions: {
    read: `View ${humanName}`,
    readDesc: `Can open ${humanName} and read its records`,
    write: `Manage ${humanName}`,
    writeDesc: `Can create, edit and delete ${humanName} records`,
  },
};

const enJson = makeI18nJson(enObj);
const plJson = makeI18nJson({
  title: humanName,
  description: `Moduł ${humanName} — dodaj opis tutaj.`,
  navigation: { title: humanName },
  permissions: {
    read: `Podgląd: ${humanName}`,
    readDesc: `Może otwierać moduł ${humanName} i przeglądać jego wpisy`,
    write: `Zarządzanie: ${humanName}`,
    writeDesc: `Może tworzyć, edytować i usuwać wpisy modułu ${humanName}`,
  },
});
const deJson = makeI18nJson({
  title: humanName,
  description: `${humanName}-Modul — Beschreibung hier hinzufügen.`,
  navigation: { title: humanName },
  permissions: {
    read: `${humanName} ansehen`,
    readDesc: `Kann ${humanName} öffnen und seine Einträge lesen`,
    write: `${humanName} verwalten`,
    writeDesc: `Kann Einträge in ${humanName} anlegen, bearbeiten und löschen`,
  },
});
const frJson = makeI18nJson({
  title: humanName,
  description: `Module ${humanName} — ajoutez votre description ici.`,
  navigation: { title: humanName },
  permissions: {
    read: `Consulter ${humanName}`,
    readDesc: `Peut ouvrir ${humanName} et lire ses entrées`,
    write: `Gérer ${humanName}`,
    writeDesc: `Peut créer, modifier et supprimer les entrées de ${humanName}`,
  },
});
const esJson = makeI18nJson({
  title: humanName,
  description: `Módulo ${humanName} — añada su descripción aquí.`,
  navigation: { title: humanName },
  permissions: {
    read: `Ver ${humanName}`,
    readDesc: `Puede abrir ${humanName} y leer sus registros`,
    write: `Gestionar ${humanName}`,
    writeDesc: `Puede crear, editar y eliminar registros de ${humanName}`,
  },
});

// ---------------------------------------------------------------------------
// Generate files
// ---------------------------------------------------------------------------

console.log(`\nGenerating frontend scaffold for module "${name}"...`);

write("module.ts", moduleTs);
write("pages/IndexPage.tsx", indexPageTsx);
touch("components/.gitkeep");
touch("hooks/.gitkeep");
write("i18n/en.json", enJson);
write("i18n/pl.json", plJson);
write("i18n/de.json", deJson);
write("i18n/fr.json", frJson);
write("i18n/es.json", esJson);
touch("types/.gitkeep");

console.log(`
Done! Next steps:
  1. The module is auto-discovered by Vite (import.meta.glob). No manual import needed.
  2. Enable the module in the backend admin panel (or seed data) to make it appear in the UI.
  3. Edit src/modules/${name}/pages/IndexPage.tsx to build your UI.
  4. Edit src/modules/${name}/module.ts to add more routes or nav items.
  5. Run: make validate-module, then make check-frontend - it names the API
     routes no screen calls yet (MODULE_QUICKSTART.md, step 7).
  6. See MODULE_QUICKSTART.md for the full guide.
`);
