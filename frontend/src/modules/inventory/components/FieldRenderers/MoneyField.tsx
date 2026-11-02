interface MoneyValue {
  amount: string;
  currency: string;
}

export function normalizeMoneyValue(
  raw: unknown,
  defaultCurrency: string | null | undefined,
): MoneyValue {
  if (raw && typeof raw === "object" && "amount" in raw) {
    const r = raw as { amount?: unknown; currency?: unknown };
    return {
      amount: typeof r.amount === "string" ? r.amount : "",
      currency:
        typeof r.currency === "string"
          ? r.currency
          : (defaultCurrency ?? "USD"),
    };
  }
  return { amount: "", currency: defaultCurrency ?? "USD" };
}
