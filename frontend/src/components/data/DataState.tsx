interface DataStateProps {
  loading: boolean;
  error: boolean;
  loadingMessage: string;
  onRetry: () => void;
}

export function DataState({ loading, error, loadingMessage, onRetry }: DataStateProps) {
  if (loading) {
    return <p className="py-10 text-sm text-[var(--strata-muted)]">{loadingMessage}</p>;
  }

  if (error) {
    return (
      <div className="mt-6 rounded-md border border-rose-200 bg-rose-50 px-4 py-4 text-sm text-rose-950" role="alert">
        <p>Unable to load workspace data. Check that the Strata backend is running.</p>
        <button className="mt-3 font-semibold text-rose-800 underline decoration-rose-300 underline-offset-4 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--strata-accent)]" onClick={onRetry} type="button">Retry</button>
      </div>
    );
  }

  return null;
}
