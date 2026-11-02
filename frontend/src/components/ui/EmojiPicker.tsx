import { useState, useMemo } from "react";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import { useTranslation } from "react-i18next";
import { Sparkles, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { FluentEmoji } from "./FluentEmoji";
import { Button } from "./Button";
import { FluentEmojiManifest } from "@/lib/fluent-emoji-manifest";
import { EMOJI_NAMES } from "@/lib/emojiNames";
import { EMOJI_CATEGORIES } from "@/lib/emojiCategories";

export interface EmojiPickerProps {
  value: string | null;
  onChange: (emoji: string | null) => void;
  className?: string;
  contextTag?: string;
}

const FLUENT_EMOJIS = new Set(Object.keys(FluentEmojiManifest));

function getAllEmojis(): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const cat of EMOJI_CATEGORIES) {
    for (const e of cat.emojis) {
      if (!seen.has(e)) {
        seen.add(e);
        result.push(e);
      }
    }
  }
  return result;
}

const ALL_EMOJIS = getAllEmojis();

function matchesSearch(emoji: string, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  const names = EMOJI_NAMES[emoji];
  if (names) {
    return names.some((kw) => kw.toLowerCase().includes(q));
  }
  return false;
}

export function EmojiPicker({ value, onChange, className }: EmojiPickerProps) {
  const { t } = useTranslation("categories");
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");

  const displayEmojis = useMemo(() => {
    const query = search.trim();
    if (query) {
      return ALL_EMOJIS.filter((e) => matchesSearch(e, query));
    }
    return ALL_EMOJIS;
  }, [search]);

  return (
    <PopoverPrimitive.Root
      open={open}
      onOpenChange={(v) => {
        setOpen(v);
        if (!v) setSearch("");
      }}
    >
      <PopoverPrimitive.Trigger asChild>
        <button
          type="button"
          aria-label={t("modal.symbolLabel", { defaultValue: "Symbol" })}
          className={cn(
            "flex items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2 text-left hover:bg-surface-raised transition-colors",
            className,
          )}
        >
          <span
            className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent-100"
            aria-hidden
          >
            {value ? (
              FLUENT_EMOJIS.has(value) ? (
                <FluentEmoji emoji={value} size={22} />
              ) : (
                <span className="text-2xl">{value}</span>
              )
            ) : (
              <Sparkles size={18} className="text-accent-700" />
            )}
          </span>
          <span className="flex flex-col text-xs">
            <span className="font-medium text-on">
              {value ??
                t("modal.symbolAuto", { defaultValue: "Auto (based on name)" })}
            </span>
            <span className="text-on-muted">
              {t("modal.symbolHelp", {
                defaultValue: "Click to choose a different emoji",
              })}
            </span>
          </span>
        </button>
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          sideOffset={6}
          align="start"
          className="z-[var(--z-popover)] w-[320px] max-h-[400px] rounded-xl border border-border bg-surface-card shadow-lg flex flex-col overflow-hidden"
        >
          <div className="p-2 border-b border-border">
            <div className="flex items-center gap-2 px-2 py-1.5 rounded-lg bg-surface">
              <Search size={14} className="text-on-muted shrink-0" />
              <input
                type="text"
                aria-label={t("modal.symbolSearch", {
                  defaultValue: "Search emoji...",
                })}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t("modal.symbolSearch", {
                  defaultValue: "Search emoji...",
                })}
                className="flex-1 bg-transparent text-sm text-on outline-none placeholder:text-on-muted/50"
                autoFocus
              />
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-2">
            {displayEmojis.length === 0 ? (
              <div className="py-8 text-center text-xs text-on-muted">
                {t("modal.symbolNoResults", {
                  defaultValue: "No emojis found",
                })}
              </div>
            ) : search ? (
              <div className="grid grid-cols-8 gap-0.5">
                {displayEmojis.map((e) => {
                  const isActive = value === e;
                  const hasFluent = FLUENT_EMOJIS.has(e);
                  return (
                    <button
                      key={e}
                      type="button"
                      onClick={() => {
                        onChange(e);
                        setOpen(false);
                        setSearch("");
                      }}
                      className={cn(
                        "flex h-8 w-8 items-center justify-center rounded-lg transition-all",
                        isActive
                          ? "bg-accent-100 ring-2 ring-accent-500"
                          : "hover:bg-surface-raised hover:scale-110",
                      )}
                    >
                      {hasFluent ? (
                        <FluentEmoji emoji={e} size={18} />
                      ) : (
                        <span className="text-lg">{e}</span>
                      )}
                    </button>
                  );
                })}
              </div>
            ) : (
              EMOJI_CATEGORIES.map((cat) => (
                <div key={cat.label} className="mb-2">
                  <div className="mb-1 text-[10px] font-medium uppercase tracking-wider text-on-muted/70 px-1">
                    {cat.label}
                  </div>
                  <div className="grid grid-cols-8 gap-0.5">
                    {cat.emojis.map((e) => {
                      const isActive = value === e;
                      const hasFluent = FLUENT_EMOJIS.has(e);
                      return (
                        <button
                          key={e}
                          type="button"
                          onClick={() => {
                            onChange(e);
                            setOpen(false);
                            setSearch("");
                          }}
                          className={cn(
                            "flex h-8 w-8 items-center justify-center rounded-lg transition-all",
                            isActive
                              ? "bg-accent-100 ring-2 ring-accent-500"
                              : "hover:bg-surface-raised hover:scale-110",
                          )}
                        >
                          {hasFluent ? (
                            <FluentEmoji emoji={e} size={18} />
                          ) : (
                            <span className="text-lg">{e}</span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))
            )}
          </div>

          <div className="p-2 border-t border-border flex items-center justify-between">
            <span className="text-[10px] text-on-muted">
              {t("modal.emojiCount", {
                fluent: FLUENT_EMOJIS.size,
                total: ALL_EMOJIS.length,
              })}
            </span>
            <Button
              type="button"
              variant="ghost"
              size="contentSm"
              onClick={() => {
                onChange(null);
                setOpen(false);
                setSearch("");
              }}
              className="text-[10px] h-6 px-2"
            >
              {t("modal.symbolAuto", { defaultValue: "Auto" })}
            </Button>
          </div>
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
