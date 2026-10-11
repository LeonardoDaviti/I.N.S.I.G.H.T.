/**
 * Everything the studio shows, found by glob (D1, D6): the markdown docs, the
 * component specimens and the prototypes. Adding a file adds it to /design;
 * there is no list to edit.
 */
import type { ComponentType } from 'react';
import { parseDoc, type DesignDoc } from './coverage';
import { docHref, type PrototypeRef } from './studio';

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

const prototypeFiles = import.meta.glob<string>('./prototypes/*/README.md', { query: '?raw', import: 'default', eager: true });

export interface Prototype extends PrototypeRef {
  readme: string;
}

/** The open prototypes (`prototypes/<yyyy-mm-dd>-<slug>/`); S5b adds the compare view. */
export const PROTOTYPES: readonly Prototype[] = Object.entries(prototypeFiles)
  .map(([path, readme]) => {
    const id = path.split('/')[2];
    return { id, label: id.replace(/^\d{4}-\d{2}-\d{2}-/, ''), readme };
  })
  .sort((a, b) => a.id.localeCompare(b.id));
