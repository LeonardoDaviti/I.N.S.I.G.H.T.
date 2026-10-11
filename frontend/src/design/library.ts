/**
 * Everything the studio shows, found by glob (D1, D6): the markdown docs, the
 * component specimens and the prototypes. Adding a file adds it to /design;
 * there is no list to edit.
 */
import type { ComponentType } from 'react';
import { parseDoc, type DesignDoc } from './coverage';
import { docHref, type PrototypeRef } from './studio';
import { PROTOTYPES } from './prototypeRegistry';
import { isOpen, prototypeAge } from './prototypes';

export { PROTOTYPES, prototypeById } from './prototypeRegistry';

const docFiles = import.meta.glob<string>('./docs/**/*.md', { query: '?raw', import: 'default', eager: true });

/** Every design doc, by its path under docs/. */
export const DOCS: readonly DesignDoc[] = Object.entries(docFiles).map(([path, text]) => parseDoc(path.replace('./docs/', ''), text));

/** The doc that lives at a studio URL. */
export function docAt(href: string): DesignDoc | undefined {
  return DOCS.find((doc) => docHref(doc) === href);
}

const specimenFiles = import.meta.glob<{ default: ComponentType }>('./specimens/components/*.tsx', { eager: true });

/** One hand-written specimen per `components/ui` primitive, named like its file. */
export const COMPONENT_SPECIMENS: ReadonlyMap<string, ComponentType> = new Map(
  Object.entries(specimenFiles)
    .map(([path, module]) => [path.replace(/^.*\//, '').replace(/\.tsx$/, ''), module.default] as const)
    .sort(([a], [b]) => a.localeCompare(b)),
);

/**
 * The prototypes for the rail (D6): open ones first, oldest first, each with
 * its status and age, so nothing rots silently.
 */
export function prototypeRefs(now: Date): PrototypeRef[] {
  return [...PROTOTYPES]
    .sort((a, b) => Number(isOpen(b)) - Number(isOpen(a)) || a.id.localeCompare(b.id))
    .map((prototype) => ({ id: prototype.id, label: prototype.slug, note: `${prototype.status} · ${prototypeAge(prototype, now)}` }));
}
