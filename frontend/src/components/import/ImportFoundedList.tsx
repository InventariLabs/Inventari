interface Props {
  /** "3 locations created" — the caller counts in its own words. */
  heading: string;
  names: string[];
}

/** What an import created beside the products, under a counted heading, so
 *  the reader learns it from the summary and not from new tiles later.
 *  Nothing is shown when the import created none. */
export function ImportFoundedList({ heading, names }: Props) {
  if (names.length === 0) return null;
  return (
    <div>
      <p className="text-[10px] font-medium text-on-muted uppercase tracking-widest mb-1">
        {heading}
      </p>
      <ul className="text-xs text-on space-y-0.5">
        {names.map((name) => (
          <li key={name}>{name}</li>
        ))}
      </ul>
    </div>
  );
}
