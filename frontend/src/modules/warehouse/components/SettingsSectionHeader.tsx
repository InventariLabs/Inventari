interface SettingsSectionHeaderProps {
  title: string;
  hint: string;
}

/** The title and one-line hint over a block of the Settings screen. */
export function SettingsSectionHeader({
  title,
  hint,
}: SettingsSectionHeaderProps) {
  return (
    <>
      <h2 className="text-sm font-semibold text-on">{title}</h2>
      <p className="text-xs text-on-secondary mt-0.5 mb-4">{hint}</p>
    </>
  );
}
