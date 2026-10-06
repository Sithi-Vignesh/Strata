export function OverviewPage() {
  return <PagePlaceholder title="Overview" />;
}

export function PagePlaceholder({ title }: { title: string }) {
  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      <p className="mt-2 text-slate-600">This screen is established for a future Strata phase.</p>
    </section>
  );
}
