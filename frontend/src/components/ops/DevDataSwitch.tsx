import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

/** sessionStorage flag set by the dev shortcut (Alt+Shift+D); survives navigation in the tab. */
export const DEV_DATA_SWITCH_FLAG = 'insight:dev-data-switch';
const SHORTCUT_EVENT = 'insight:dev-data-switch';

function readFlag(): boolean {
  try {
    return window.sessionStorage.getItem(DEV_DATA_SWITCH_FLAG) === '1';
  } catch {
    return false;
  }
}

function writeFlag(on: boolean) {
  try {
    if (on) window.sessionStorage.setItem(DEV_DATA_SWITCH_FLAG, '1');
    else window.sessionStorage.removeItem(DEV_DATA_SWITCH_FLAG);
  } catch {
    // Storage blocked: the switch then only follows `?data=`.
  }
  window.dispatchEvent(new Event(SHORTCUT_EVENT));
}

/** Alt+Shift+D toggles the flag; every mounted switch listens for the change. */
function useDevSwitchFlag(): boolean {
  const [on, setOn] = useState(readFlag);
  useEffect(() => {
    if (!import.meta.env.DEV) return undefined;
    const sync = () => setOn(readFlag());
    const onKey = (event: KeyboardEvent) => {
      if (event.altKey && event.shiftKey && !event.metaKey && !event.ctrlKey && event.code === 'KeyD') {
        event.preventDefault();
        writeFlag(!readFlag());
      }
    };
    window.addEventListener(SHORTCUT_EVENT, sync);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener(SHORTCUT_EVENT, sync);
      window.removeEventListener('keydown', onKey);
    };
  }, []);
  return on;
}

/**
 * The dev-only `?data=` switch (spec §F.7, break-ui): flips a list between live
 * data and its worst-case, empty, one and huge fixtures. Plain chrome, fixed at
 * the bottom centre, no animation; never rendered in a production build, and in
 * dev only once asked for (a `?data=` URL or Alt+Shift+D), so the owner's
 * preview on the dev server reads like the real app.
 */
export default function DevDataSwitch({ options }: { options: readonly string[] }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const flag = useDevSwitchFlag();
  if (!import.meta.env.DEV) return null;
  if (!flag && !searchParams.has('data')) return null;
  const current = searchParams.get('data') ?? 'live';
  const choose = (value: string) => {
    // Keep the switch up after "Live" drops `?data=` from the URL.
    if (!flag) writeFlag(true);
    const next = new URLSearchParams(searchParams);
    if (value === 'live') next.delete('data');
    else next.set('data', value);
    setSearchParams(next, { replace: true });
  };
  return (
    <div
      role="group"
      aria-label="Demo data (dev only, Alt+Shift+D hides)"
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
