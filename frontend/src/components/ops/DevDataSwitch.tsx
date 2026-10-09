import { useSearchParams } from 'react-router-dom';

/**
 * The dev-only `?data=` switch (spec §F.7, break-ui): flips a list between live
 * data and its worst-case, empty, one and huge fixtures. Plain chrome, fixed at
 * the bottom centre, no animation; never rendered in a production build.
 */
export default function DevDataSwitch({ options }: { options: readonly string[] }) {
  const [searchParams, setSearchParams] = useSearchParams();
  if (!import.meta.env.DEV) return null;
  const current = searchParams.get('data') ?? 'live';
  const choose = (value: string) => {
    const next = new URLSearchParams(searchParams);
    if (value === 'live') next.delete('data');
    else next.set('data', value);
    setSearchParams(next, { replace: true });
  };
  return (
    <div
      role="group"
      aria-label="Demo data (dev only)"
      className="fixed bottom-3 left-1/2 z-40 flex -translate-x-1/2 gap-0.5 rounded-md border border-line-strong bg-raised p-0.5 font-sans text-[0.75rem] shadow-overlay"
    >
      {['live', ...options].map((value) => (
        <button
          key={value}
          type="button"
          aria-pressed={current === value}
          onClick={() => choose(value)}
          className={`whitespace-nowrap rounded-sm px-2.5 py-1 ${current === value ? 'bg-inverse text-inverse-fg' : 'text-fg-2 hover:text-fg'}`}
        >
          {value === 'live' ? 'Live' : value === 'worst' ? 'Worst case' : value.charAt(0).toUpperCase() + value.slice(1)}
        </button>
      ))}
    </div>
  );
}
