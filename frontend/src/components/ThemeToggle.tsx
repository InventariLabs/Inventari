import { useEffect, useRef, useState } from "react";
import { ChevronDown, Monitor, Moon, Sun } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { useThemeStore, type ThemeMode } from "@/store/themeStore";

const modes = ["light", "dark", "system"] as const;

const modeIcons = {
  light: Sun,
  dark: Moon,
  system: Monitor,
} as const;

/**
 * The theme control — a picker, not a carousel.
 *
 * It used to cycle light → dark → system on click, which asks the reader to
 * know the order and hides which of the three is chosen. Worse, two of the
 * three look identical while the system is light: the click that moves from
 * "Light" to "Follow system" changes nothing on screen and reads as a broken
 * button.
 *
 * So it is built like the `LanguageSelector` standing next to it in the user
 * menu: a trigger showing the current state and a list with the active option
 * marked. `themeStore` is untouched — what changes is how its three states are
 * offered, not what they do.
 */
export function ThemeToggle() {
  const { t } = useTranslation("common");
  const { mode, setMode } = useThemeStore();
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const current: ThemeMode = modes.includes(mode as (typeof modes)[number])
    ? mode
    : "system";
  const Icon = modeIcons[current];
  // The accessible name used to be a bare "Theme", which said nothing about
  // which of the three states the button was in.
  const stateLabel = t(`settings.theme_${current}` as const);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleSelect = (next: ThemeMode) => {
    setMode(next);
    setIsOpen(false);
  };

  return (
    <div className="relative" ref={dropdownRef}>
      <Button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        variant="ghost"
        size="contentSm"
        className="px-2 py-1 hover:opacity-70 hover:bg-transparent"
        aria-haspopup="menu"
        aria-expanded={isOpen}
        aria-label={`${t("settings.theme")}: ${stateLabel}`}
        title={stateLabel}
      >
        <Icon size={18} />
        <ChevronDown
          size={14}
          className={`text-on-muted transition-transform duration-200 ${isOpen ? "rotate-180" : ""}`}
        />
      </Button>

      {isOpen && (
        <div
          role="menu"
          className="absolute top-full mt-2 right-0 w-44 bg-surface-card rounded-2xl shadow-md z-[var(--z-module-nav)] overflow-hidden animate-in zoom-in-95 duration-150 origin-top-right"
        >
          <div className="py-1">
            {modes.map((option) => {
              const OptionIcon = modeIcons[option];
              const isActive = current === option;
              return (
                <Button
                  type="button"
                  key={option}
                  role="menuitemradio"
                  aria-checked={isActive}
                  onClick={() => handleSelect(option)}
                  variant="ghost"
                  size="contentSm"
                  className={`w-full px-4 py-2.5 justify-between text-sm ${
                    isActive
                      ? "bg-primary-50 hover:bg-primary-50 text-primary-700 font-semibold"
                      : "text-on-secondary hover:bg-surface"
                  }`}
                >
                  <span className="flex items-center gap-2">
                    <OptionIcon size={15} />
                    {t(`settings.theme_${option}` as const)}
                  </span>
                  {isActive && (
                    <div className="w-1.5 h-1.5 rounded-full bg-primary-500" />
                  )}
                </Button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
