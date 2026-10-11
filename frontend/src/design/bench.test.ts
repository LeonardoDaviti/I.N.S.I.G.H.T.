import { describe, expect, it } from 'vitest';

import { benchHref, benchSubjects, parseBench, type BenchPage } from './bench';
import { parsePrototype } from './prototypes';

const prototype = (id: string, status: string) => parsePrototype(
  id,
  `\`\`\`meta\nhypothesis: H\nprinciples: P4\npage: post\nstates: long-title, article\nstatus: ${status}\ncreated: ${id.slice(0, 10)}\n\`\`\`\n# T`,
);
const prototypes = [prototype('2026-10-10-title-wrap', 'review'), prototype('2026-10-01-old', 'rejected'), prototype('2026-10-11-new', 'draft')];
const pages: BenchPage[] = [
  { name: 'reader', title: 'Reader', states: ['normal', 'empty', 'loading'] },
  { name: 'post', title: 'Post', states: ['article', 'long-title'] },
  { name: 'shell', title: 'Shell', states: ['cmdk-many', 'narrow-topbar'] },
];
const widthOf = (page: string, state: string) => (page === 'shell' && state === 'narrow-topbar' ? 320 : undefined);
const parse = (query: string) => parseBench(new URLSearchParams(query), { prototypes, pages, widthOf });

describe('the Bench subjects', () => {
  it('offers open prototypes first (oldest first), then pages, then closed prototypes', () => {
    expect(benchSubjects(prototypes, pages).map((group) => [group.label, group.subjects.map((subject) => subject.id)])).toEqual([
      ['open prototypes', ['2026-10-10-title-wrap', '2026-10-11-new']],
      ['pages', ['reader', 'post', 'shell']],
      ['closed prototypes', ['2026-10-01-old']],
    ]);
  });
});

describe('parseBench', () => {
  it('opens on the oldest open prototype: current page against it, on its first state, 1400, dark', () => {
    expect(parse('mode=bench')).toEqual({
      subject: '2026-10-10-title-wrap', prototype: '2026-10-10-title-wrap', page: 'post', states: ['long-title', 'article'],
      left: 'long-title', right: 'long-title', widths: [1400, 390, 320], width: 1400, theme: 'dark', drawer: true,
    });
  });

  it('shares one state between current and prototype', () => {
    expect(parse('subject=2026-10-10-title-wrap&state=article&left=long-title')).toMatchObject({ left: 'article', right: 'article' });
  });

  it('compares two states of a page, the second state on the right by default', () => {
    expect(parse('subject=reader')).toMatchObject({ prototype: undefined, page: 'reader', left: 'normal', right: 'empty' });
    expect(parse('subject=reader&left=loading&right=normal&width=390&theme=light&doc=hide')).toMatchObject({
      left: 'loading', right: 'normal', width: 390, theme: 'light', drawer: false,
    });
  });

  it('offers 1400, 390 and the narrowest phone, 320, on every subject', () => {
    expect(parse('subject=shell&width=320')).toMatchObject({ widths: [1400, 390, 320], width: 320 });
    expect(parse('subject=2026-10-10-title-wrap&width=320')).toMatchObject({ widths: [1400, 390, 320], width: 320 });
  });

  it('falls back on anything unknown: subject, state, width, theme', () => {
    expect(parse('subject=nope&state=huge&width=7&theme=sepia')).toMatchObject({
      subject: '2026-10-10-title-wrap', left: 'long-title', width: 1400, theme: 'dark',
    });
  });

  it('opens on the first page when no prototype is open', () => {
    expect(parseBench(new URLSearchParams(), { prototypes: [], pages, widthOf })).toMatchObject({ subject: 'reader', page: 'reader' });
  });
});

describe('benchHref', () => {
  it('links Bench on a subject', () => {
    expect(benchHref('2026-10-10-title-wrap')).toBe('/design?mode=bench&subject=2026-10-10-title-wrap');
  });
});
