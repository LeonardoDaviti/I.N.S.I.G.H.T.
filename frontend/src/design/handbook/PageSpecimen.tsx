import { useSearchParams } from 'react-router-dom';
import Segmented from '../Segmented';
import SpecimenSlot from '../SpecimenSlot';
import { frameScenario } from '../fixtures/scenarios';
import { SPECIMEN_THEMES, SPECIMEN_WIDTHS, type SpecimenTheme } from '../specimen';

/**
 * The specimen under a page doc, with its controls. State, width and theme
 * live in the URL (`?state=&width=&theme=`) so a specimen can be linked and
 * screenshotted (D9); the defaults leave the URL clean. A state with its own
 * width (the 320px top bar) adds it to the widths and opens at it.
 */
export default function PageSpecimen({ page, states }: { page: string; states: readonly string[] }) {
  const [params, setParams] = useSearchParams();
  const state = states.find((name) => name === params.get('state')) ?? states[0];
  const own = (name: string) => frameScenario(page, name)?.width;
  const widths = [...new Set([...SPECIMEN_WIDTHS, ...states.map(own).filter((value): value is number => value !== undefined)])].map(String);
  const defaultWidth = String(own(state) ?? SPECIMEN_WIDTHS[0]);
  const width = Number(widths.find((value) => value === params.get('width')) ?? defaultWidth);
  const theme = (SPECIMEN_THEMES.find((value) => value === params.get('theme')) ?? SPECIMEN_THEMES[0]) as SpecimenTheme;

  const choose = (key: string, value: string, fallback: string) =>
    setParams((current) => {
      const next = new URLSearchParams(current);
      if (value === fallback) next.delete(key);
      else next.set(key, value);
      return next;
    }, { replace: true });

  return (
    <section aria-label="Specimen" className="mt-14 border-t border-line pt-6">
      <div className="mb-5 flex flex-wrap items-center gap-x-6 gap-y-3">
        <h2 className="text-[0.8125rem] lowercase text-fg-3">specimen</h2>
        {states.length > 1 ? (
          <Segmented size="sm" label="State" value={state} options={states} onChange={(value) => choose('state', value, states[0])} />
        ) : null}
        <div className="flex flex-wrap items-center gap-3 sm:ml-auto">
          <Segmented size="sm" label="Width" value={String(width)} options={widths} onChange={(value) => choose('width', value, defaultWidth)} />
          <Segmented size="sm" label="Theme" value={theme} options={SPECIMEN_THEMES} onChange={(value) => choose('theme', value, SPECIMEN_THEMES[0])} />
        </div>
      </div>
      <SpecimenSlot page={page} state={state} width={width} theme={theme} />
    </section>
  );
}
