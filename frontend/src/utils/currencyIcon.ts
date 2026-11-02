import {
  Banknote,
  DollarSign,
  Euro,
  IndianRupee,
  JapaneseYen,
  PoundSterling,
  SwissFranc,
  type LucideIcon,
} from "lucide-react";

/**
 * The icon that goes next to an amount.
 *
 * A dollar sign beside a złoty total is the same lie as formatting the amount
 * with the wrong symbol — and a card that hard-codes one icon tells it to
 * every organization. Currencies without a glyph of their own get the neutral
 * banknote, which claims nothing.
 */
const ICONS: Record<string, LucideIcon> = {
  USD: DollarSign,
  AUD: DollarSign,
  CAD: DollarSign,
  NZD: DollarSign,
  EUR: Euro,
  GBP: PoundSterling,
  JPY: JapaneseYen,
  CNY: JapaneseYen,
  INR: IndianRupee,
  CHF: SwissFranc,
};

export function currencyIcon(currency?: string | null): LucideIcon {
  if (!currency) return Banknote;
  return ICONS[currency.toUpperCase()] ?? Banknote;
}
