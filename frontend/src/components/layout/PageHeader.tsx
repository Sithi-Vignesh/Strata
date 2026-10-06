interface PageHeaderProps {
  title: string;
  description?: string;
}

export function PageHeader({ title, description }: PageHeaderProps) {
  return (
    <header className="border-b border-[var(--strata-border)] pb-6">
      <h1 className="text-2xl font-semibold tracking-[-0.02em] text-[var(--strata-text)] sm:text-3xl">{title}</h1>
      {description && <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--strata-muted)]">{description}</p>}
    </header>
  );
}
