import { useTranslation } from "react-i18next";
import { AlertTriangle, Check } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { DynamicIcon } from "@/components/ui/DynamicIcon";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { cn } from "@/lib/utils";
import type { ModuleInfo } from "@/types";

interface ModuleStoreCardProps {
  module: ModuleInfo;
  isEnabled: boolean;
  isBusy: boolean;
  /**
   * The modules this one requires that are not switched on here, named as
   * their cards name them; empty when nothing is missing.
   */
  missingRequirementNames: string;
  /** Declared companions that are not switched on here, named likewise. */
  missingCompanionNames: string;
  onToggle: () => void;
}

/** What the registry writes as the author of a module that came with the tree. */
const CORE_TEAM_AUTHOR = "Core Team";

/**
 * The manifest facts under the description — and who, if anyone, vouches
 * for them.
 *
 * The author and the licence come off the package's own `module.yaml`,
 * merged into the manifest at install time (without that merge every
 * community module introduced itself as the core team). That merge cannot
 * make them true: a package writing its own author line is a package
 * vouching for itself. The signature can, because the digest covers
 * `module.yaml` — so a verified install names the key, and an unsigned one
 * says plainly that these are the package's own words. A module that came
 * with the tree claims neither: its code is in the repository.
 */
function ModuleMetaLine({
  version,
  author,
  license,
  signatureStatus,
  signedBy,
}: {
  version?: string;
  author?: string | null;
  license?: string | null;
  signatureStatus?: "verified" | "unsigned" | null;
  signedBy?: string | null;
}) {
  const { t } = useTranslation("common");
  // The registry stamps "Core Team" on every module of the tree: a registry
  // value, not a name, so it is said in the reader's language.
  const shownAuthor =
    author === CORE_TEAM_AUTHOR && !signatureStatus
      ? t("appStore.coreTeam")
      : author;
  const identity = [shownAuthor, license].filter(Boolean).join(" · ");
  const declared = signatureStatus === "unsigned" && identity;
  const parts = [
    version && `v${version}`,
    declared ? `${t("appStore.declaredPrefix")} ${identity}` : identity,
  ].filter(Boolean);
  if (parts.length === 0 && !signatureStatus) return null;
  return (
    <>
      {parts.length > 0 && (
        <p className="text-[10px] text-on-secondary mt-1 font-mono truncate">
          {parts.join(" · ")}
        </p>
      )}
      {signatureStatus === "verified" && signedBy && (
        <p
          className="text-[10px] text-on-secondary mt-0.5 truncate"
          title={t("appStore.signedByHint")}
        >
          {t("appStore.signedBy", { key: signedBy })}
        </p>
      )}
      {signatureStatus === "unsigned" && (
        <p
          className="text-[10px] text-on-warning mt-0.5"
          title={t("appStore.unsignedPackageHint")}
        >
          {t("appStore.unsignedPackage")}
        </p>
      )}
    </>
  );
}

/**
 * The module's project page, if the author declared one. Renders the hostname
 * as the link text — it is language-neutral, and it shows where the link
 * goes. A missing or non-HTTP(S) URL shows nothing: a `javascript:` href has
 * no business in a card that renders third-party package metadata.
 */
function ModuleHomepageLink({ homepage }: { homepage?: string | null }) {
  if (!homepage) return null;
  let href: URL;
  try {
    href = new URL(homepage);
  } catch {
    return null;
  }
  if (href.protocol !== "https:" && href.protocol !== "http:") return null;
  return (
    <a
      href={href.href}
      target="_blank"
      rel="noreferrer"
      className="block text-[10px] text-primary-700 dark:text-primary-500 mt-0.5 truncate hover:underline"
    >
      {href.hostname}
    </a>
  );
}

/**
 * Every trust level draws its badge, `community` included: the row also
 * carries badges unrelated to trust (enabled, always on, needs an API
 * key), so a card without a trust badge does not read as "the base
 * level" — it reads as a badge that failed to load. The level is the one
 * fact the store exists to show, and the operator warning it colours was
 * written for exactly the community card.
 */
/**
 * Which trust badge a card wears. "Core" reads as "always on" everywhere else
 * on the page, so a module the core team ships but an administrator can switch
 * off (API Keys) is badged for what it is, an official module — not "Core"
 * beside "Disabled · Activate".
 */
function trustLevel(moduleType: string, isAlwaysOn: boolean): string {
  return moduleType === "core" && !isAlwaysOn ? "official" : moduleType;
}

const TRUST_BADGES: Record<string, string> = {
  core: "appStore.trust_core",
  official: "appStore.trust_official",
  cloud: "appStore.trust_cloud",
  community: "appStore.trust_community",
};

/**
 * The title row and every badge that qualifies it. Split out of the card
 * so the card decides layout and behaviour while this component decides
 * which facts are worth a badge.
 */
function ModuleCardBadges({
  module,
  isEnabled,
  isAlwaysOn,
  hasOverrides,
}: {
  module: ModuleInfo;
  isEnabled: boolean;
  isAlwaysOn: boolean;
  hasOverrides: boolean;
}) {
  const { t } = useTranslation(["common", "modules"]);
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {/* h2, not h3: the shell header carries the page's h1, so the module
          name is the page's second level — a jump straight to h3 left a
          level out of the heading tree. */}
      <h2 className="font-semibold text-on text-sm leading-tight">
        {t(`modules.${module.name}.name`, {
          ns: "modules",
          defaultValue: module.display_name,
        })}
      </h2>
      {/* The one trust fact the store exists to show — every level draws
          its badge, the base level included. */}
      {module.module_type in TRUST_BADGES && (
        <Badge
          variant={
            trustLevel(module.module_type, isAlwaysOn) === "core"
              ? "default"
              : "secondary"
          }
          className="text-[10px] px-1.5 py-0"
        >
          {t(TRUST_BADGES[trustLevel(module.module_type, isAlwaysOn)])}
        </Badge>
      )}
      {isEnabled ? (
        <Badge variant="success" className="text-[10px] px-1.5 py-0">
          <Check size={8} className="mr-0.5" />
          {t("modules:enabled")}
        </Badge>
      ) : (
        // The state used to live only in the button label, and switching a
        // module off left its card with no status at all — an admin tidying
        // the store could not tell a switched-off module from one waiting
        // to be switched on.
        <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
          {t("modules:disabled")}
        </Badge>
      )}
      {isAlwaysOn && (
        <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
          {t("appStore.alwaysOn")}
        </Badge>
      )}
      {module.degraded && (
        <Badge variant="warning" className="text-[10px] px-1.5 py-0">
          {t("appStore.degraded")}
        </Badge>
      )}
      {module.requires_api_key && (
        <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
          {t("appStore.needsApiKey")}
        </Badge>
      )}
      {/* The registry records whether a module's screens are on this
          installation. Nothing carried that to the one place where somebody
          decides to switch a module on, so an install that landed half a
          module still drew an ordinary card. */}
      {module.frontend_state === "headless" && (
        <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
          {t("appStore.noScreens")}
        </Badge>
      )}
      {module.frontend_state === "incomplete" && (
        <Badge variant="warning" className="text-[10px] px-1.5 py-0">
          <AlertTriangle size={8} className="mr-0.5" />
          {t("appStore.screensMissing")}
        </Badge>
      )}
      {/* "UI" was a literal in the JSX, explained only in a `title`
          attribute — invisible on a phone and to a screen reader. */}
      {hasOverrides && (
        <Badge variant="warning" className="text-[10px] px-1.5 py-0">
          <AlertTriangle size={8} className="mr-0.5" />
          {t("appStore.changesUi")}
        </Badge>
      )}
    </div>
  );
}

/**
 * The declared resource words, as a person who runs a shop would say them.
 * A community module may declare a word not listed here; it is shown as
 * written rather than hidden.
 */
const CAPABILITY_LABELS: Record<string, string> = {
  database: "appStore.capability_database",
  filesystem: "appStore.capability_filesystem",
  process: "appStore.capability_process",
  network: "appStore.capability_network",
};

/**
 * What the module declares it needs — this is information
 * for the operator, not a boundary, and the store is where the decision
 * to switch a module on is made.
 */
function CapabilitiesLine({ capabilities }: { capabilities?: string[] }) {
  const { t } = useTranslation("common");
  if (!capabilities || capabilities.length === 0) return null;
  const list = capabilities
    .map((c) => (c in CAPABILITY_LABELS ? t(CAPABILITY_LABELS[c]) : c))
    .join(", ");
  return (
    <p className="text-[10px] text-on-secondary mt-0.5 truncate">
      {t("appStore.capabilities", { list })}
    </p>
  );
}

/**
 * One tile in the module store.
 *
 * Everything it says about the module comes from `GET /modules/available`.
 * It used to read three of those facts off the frontend launcher tile
 * instead — the category, the icon and whether the module could be switched
 * off — which only modules with a tile declare. Six had none, so their cards
 * drew an empty coloured square and fell out of every category filter, and
 * two always-on modules got a Deactivate button that could only come back 403.
 *
 * The launcher tile still supplies the accent colour, which is a matter of
 * how the module looks in this build rather than what it is.
 */
export default function ModuleStoreCard({
  module,
  isEnabled,
  isBusy,
  missingRequirementNames,
  missingCompanionNames,
  onToggle,
}: ModuleStoreCardProps) {
  const { t } = useTranslation(["common", "modules"]);

  const color =
    moduleRegistry.getModule(module.name)?.launcher?.color ?? "bg-primary-500";
  const isAlwaysOn = module.is_always_on === true;
  const hasOverrides = moduleRegistry.hasOverrides(module.name);

  return (
    // `h-full` plus a column layout: the grid stretches every card to the
    // tallest in its row, and without it the Activate buttons of neighbouring
    // cards sat at three different heights.
    <Card
      className={cn(
        "flex h-full flex-col p-4 transition-all",
        isEnabled
          ? "border-primary-500/20 bg-primary-500/5 dark:border-primary-500/15 dark:bg-primary-500/10"
          : "border-border bg-surface",
      )}
    >
      <div className="flex flex-1 items-start gap-3">
        <div
          className={cn(
            "w-11 h-11 rounded-xl flex items-center justify-center shrink-0",
            color,
          )}
          aria-hidden="true"
        >
          {/* From the manifest, so a module without a launcher tile still
              draws something. An unknown name resolves to a package, never to
              an empty square. */}
          <DynamicIcon
            name={module.icon || "box"}
            size={22}
            className="text-white"
            strokeWidth={2}
          />
        </div>

        <div className="flex-1 min-w-0">
          <ModuleCardBadges
            module={module}
            isEnabled={isEnabled}
            isAlwaysOn={isAlwaysOn}
            hasOverrides={hasOverrides}
          />

          <p className="text-on-secondary text-xs mt-1 leading-snug line-clamp-2">
            {t(`modules.${module.name}.description`, {
              ns: "modules",
              defaultValue: module.description,
            })}
          </p>

          {/* Both facts arrive from the API and had no reader here:
              `nutrition` comes back degraded and its card looked like every
              other one. They belong before the decision to switch a module on,
              not after. */}
          {module.degraded && (
            <p className="text-xs text-on-warning mt-1 leading-snug">
              {t("appStore.degradedHint")}
            </p>
          )}
          {module.requires_api_key && (
            <p className="text-xs text-on-secondary mt-1 leading-snug">
              {t("appStore.needsApiKeyHint")}
            </p>
          )}
          {module.frontend_state === "headless" && (
            <p className="text-xs text-on-secondary mt-1 leading-snug">
              {t("appStore.noScreensHint")}
            </p>
          )}
          {module.frontend_state === "incomplete" && (
            <p className="text-xs text-on-warning mt-1 leading-snug">
              {t("appStore.screensMissingHint")}
            </p>
          )}
          {/* An override only takes effect while the module is on, so the
              sentence is in the tense that is true. */}
          {hasOverrides && (
            <p className="text-xs text-on-warning mt-1 leading-snug">
              {isEnabled
                ? t("appStore.changesUiHint")
                : t("appStore.changesUiHintOff")}
            </p>
          )}
          {/* A requirement does block it: said before the press, not only
              in the refusal after it. */}
          {!isEnabled && !isAlwaysOn && missingRequirementNames && (
            <p className="text-xs text-on-warning mt-1 leading-snug">
              {t("appStore.requiresHint", { names: missingRequirementNames })}
            </p>
          )}
          {/* A soft companion never blocks enabling — it is a fact before the
              decision, like the other hints. Only a module that is off has a
              decision pending, so an enabled or always-on card says nothing. */}
          {!isEnabled && !isAlwaysOn && missingCompanionNames && (
            <p className="text-xs text-on-warning mt-1 leading-snug">
              {t("appStore.optionalCompanionsHint", {
                names: missingCompanionNames,
              })}
            </p>
          )}
          <ModuleMetaLine
            version={module.version}
            author={module.author}
            license={module.license}
            signatureStatus={module.signature_status}
            signedBy={module.signed_by}
          />
          <CapabilitiesLine capabilities={module.capabilities} />
          <ModuleHomepageLink homepage={module.homepage} />
        </div>
      </div>

      <div className="mt-3 flex justify-end">
        {isAlwaysOn ? (
          <p className="text-xs text-on-secondary leading-snug text-right">
            {t("appStore.alwaysOnHint")}
          </p>
        ) : (
          <Button
            variant={isEnabled ? "secondary" : "primary"}
            size="sm"
            isLoading={isBusy}
            onClick={onToggle}
          >
            {isEnabled ? t("appStore.deactivate") : t("appStore.activate")}
          </Button>
        )}
      </div>
    </Card>
  );
}
