interface GenomePillsProps {
  genome: Record<string, string>;
}

/**
 * Creative DNA pill row — mirrors the `.genome-pills` block in the
 * Jinja report templates. One pill per slot with the slot name in
 * muted text and the value in full weight.
 */
export function GenomePills({ genome }: GenomePillsProps) {
  const entries = Object.entries(genome);
  if (entries.length === 0) return null;

  return (
    <div className="mt-3 flex flex-wrap">
      {entries.map(([slot, value]) => (
        <span
          key={slot}
          className="mb-1 mr-1 inline-flex items-center gap-1 rounded bg-[var(--bg-secondary)] px-2.5 py-0.5 text-[11px]"
        >
          <span className="text-[var(--text-tertiary)]">{slot}:</span>
          <span className="font-medium text-[var(--text)]">{value}</span>
        </span>
      ))}
    </div>
  );
}
