/**
 * The prototype registry (Design Studio D6), found by glob: adding a folder
 * under `prototypes/` registers it, deleting it retires it; there is no list
 * to edit. READMEs (and an optional `doc.diff`) load with the studio; each
 * prototype's index.tsx loads only inside the frame that renders it.
 */
import { lazy, type ComponentType, type LazyExoticComponent, type ReactNode } from 'react';
import { parsePrototype, type Prototype } from './prototypes';

const readmes = import.meta.glob<string>('./prototypes/*/README.md', { query: '?raw', import: 'default', eager: true });
const diffs = import.meta.glob<string>('./prototypes/*/doc.diff', { query: '?raw', import: 'default', eager: true });

/** The folder name of a glob path: `./prototypes/<id>/README.md` → `<id>`. */
const folder = (path: string) => path.split('/')[2];

/** Every prototype, oldest first. */
export const PROTOTYPES: readonly Prototype[] = Object.entries(readmes)
  .map(([path, readme]) => parsePrototype(folder(path), readme, diffs[`./prototypes/${folder(path)}/doc.diff`]))
  .sort((a, b) => a.id.localeCompare(b.id));

export function prototypeById(id: string): Prototype | undefined {
  return PROTOTYPES.find((prototype) => prototype.id === id);
}

/**
 * A prototype's index.tsx: its default export receives the real page (the
 * app's routes, inside the shell, on the frame's fixtures) as `children`. An
 * override wraps them (a style, a context); a replacement renders something
 * else and may ignore them.
 */
export type PrototypeComponent = ComponentType<{ children: ReactNode }>;

const modules = import.meta.glob<{ default: PrototypeComponent }>('./prototypes/*/index.tsx');
const loaded = new Map<string, LazyExoticComponent<PrototypeComponent>>();

/** The prototype's component, lazily (render it under Suspense); undefined when it has no index.tsx. */
export function prototypeComponent(id: string): LazyExoticComponent<PrototypeComponent> | undefined {
  const load = modules[`./prototypes/${id}/index.tsx`];
  if (!load) return undefined;
  if (!loaded.has(id)) loaded.set(id, lazy(load));
  return loaded.get(id);
}
