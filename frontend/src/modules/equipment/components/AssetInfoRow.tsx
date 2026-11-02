interface InfoRowProps {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode | null | undefined;
}

export function InfoRow({ icon, label, value }: InfoRowProps) {
  const isEmpty = value == null || value === "";
  return (
    <div className="flex items-start gap-3 py-2 border-b border-border last:border-0">
      <div className="flex-shrink-0 w-4 mt-0.5 text-on-muted flex justify-center">
        {icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-xs text-on-muted mb-0.5">{label}</div>
        <div className="text-sm text-on font-medium">
          {isEmpty ? "—" : value}
        </div>
      </div>
    </div>
  );
}
