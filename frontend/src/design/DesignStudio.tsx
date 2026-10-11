import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import Kbd from '../components/ui/Kbd';
import Segmented from './Segmented';
import { DEFAULT_MODE, MODES, parseMode, stepMode, type StudioMode } from './modes/modes';
import { isEditable } from '../lib/shortcuts';
import HandbookMode from './modes/HandbookMode';
import WallMode from './modes/WallMode';
import BenchMode from './modes/BenchMode';

/** The same address in another mode; Handbook, the default, leaves no `?mode=`. */
function withMode(params: URLSearchParams, mode: StudioMode): URLSearchParams {
  const next = new URLSearchParams(params);
  if (mode === DEFAULT_MODE) next.delete('mode');
  else next.set('mode', mode);
  return next;
}

/**
 * The Design Studio at /design (plan/INSIGHT_design_studio_plan.md): one home
 * for the principles, the system, every page and the prototypes, read from
 * the files in src/design. A lazy route chunk, so the reader never pays for
 * it (D8). The header holds the mode toggle; ← → step modes from anywhere but
 * a field.
 */
export default function DesignStudio() {
  const [params, setParams] = useSearchParams();
  const mode = parseMode(params.get('mode'));

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
      if (isEditable(event.target)) return;
      event.preventDefault();
      setParams((current) => withMode(current, stepMode(mode, event.key === 'ArrowRight' ? 1 : -1)));
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [mode, setParams]);

  const chooseMode = (next: StudioMode) => setParams((current) => withMode(current, next));

  return (
    <div className="design-studio">
      <header className="material sticky top-topbar z-20 border-b border-line">
        <div className="mx-auto flex h-12 w-full max-w-[90rem] items-center justify-between gap-4 px-4 sm:px-6">
          <p className="text-[0.9375rem] font-semibold tracking-[-0.01em] text-fg">
            design studio
          </p>
          <div className="flex items-center gap-3">
            <span aria-hidden="true" className="hidden items-center gap-1 text-[0.75rem] text-fg-3 sm:inline-flex">
              <Kbd>←</Kbd><Kbd>→</Kbd>
            </span>
            <Segmented label="Studio mode" value={mode} options={MODES} onChange={chooseMode} />
          </div>
        </div>
      </header>
      {mode === 'handbook' ? <HandbookMode /> : mode === 'wall' ? <WallMode /> : <BenchMode />}
    </div>
  );
}
