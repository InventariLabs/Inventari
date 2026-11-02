import { useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { LANGUAGES, communityCoverage, type Language } from "@/i18n/languages";
import { useLanguagePreference } from "@/hooks/useLanguagePreference";
import { ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/Button";

interface LanguageSelectorProps {
  isUp?: boolean;
  align?: "left" | "right";
}

export function LanguageSelector({
  isUp = false,
  align = "right",
}: LanguageSelectorProps) {
  const { t } = useTranslation("common");
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const { language: currentLanguageCode, changeLanguage } =
    useLanguagePreference();
  const currentLanguage =
    LANGUAGES.find((l) => l.code === currentLanguageCode) || LANGUAGES[0];

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

  const handleLanguageChange = (newLang: Language) => {
    setIsOpen(false);
    return changeLanguage(newLang);
  };

  return (
    <div className="relative" ref={dropdownRef}>
      <Button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        variant="ghost"
        size="contentSm"
        // The button reads "EN": the name starts with what is on screen (a
        // voice-control user says what they see) and then says what it is
        // for, the word the profile screen uses for the picker.
        aria-label={`${currentLanguage.name}, ${t("settings.language", "Language")}: ${currentLanguage.fullName}`}
        aria-expanded={isOpen}
        className="min-h-11 px-3 py-1 md:min-h-0 md:px-2 hover:opacity-70 hover:bg-transparent"
      >
        <span className="text-xs font-medium text-on-secondary">
          {currentLanguage.name}
        </span>
        <ChevronDown
          size={14}
          className={`text-on-muted transition-transform duration-200 ${isOpen ? "rotate-180" : ""}`}
        />
      </Button>

      {isOpen && (
        <div
          className={`absolute ${isUp ? "bottom-full mb-2" : "top-full mt-2"} ${align === "right" ? "right-0" : "left-0"} w-max min-w-32 max-w-64 bg-surface-card rounded-2xl shadow-md z-[var(--z-module-nav)] overflow-hidden animate-in zoom-in-95 duration-150 ${isUp ? (align === "right" ? "origin-bottom-right" : "origin-bottom-left") : align === "right" ? "origin-top-right" : "origin-top-left"}`}
        >
          <div className="py-1">
            {LANGUAGES.map((lang) => (
              <Button
                type="button"
                key={lang.code}
                onClick={() => handleLanguageChange(lang.code)}
                variant="ghost"
                size="contentSm"
                className={`w-full px-4 py-2.5 justify-between text-sm ${
                  currentLanguageCode === lang.code
                    ? "bg-primary-50 hover:bg-primary-50 text-primary-700 font-semibold"
                    : "text-on-secondary hover:bg-surface"
                }`}
              >
                <span className="flex flex-col items-start text-left">
                  <span>{lang.fullName}</span>
                  {communityCoverage(lang.code) !== null && (
                    <span className="text-xs font-normal text-on-muted">
                      {t("settings.communityLanguage", {
                        percent: communityCoverage(lang.code),
                      })}
                    </span>
                  )}
                </span>
                {currentLanguageCode === lang.code && (
                  <div className="w-1.5 h-1.5 rounded-full bg-primary-500" />
                )}
              </Button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
