import { describe, expect, it } from 'vitest';

import { parseDoc } from './coverage';
import { docBody, docHref, docTitle, railGroups } from './studio';

describe('a studio doc', () => {
  const doc = parseDoc('pages/reader.md', '```meta\nkind: page\nstates: normal\n```\n\n# Reader\n\nCode: `pages/ReaderPage.tsx`.\n');

  it('reads without its meta block', () => {
    expect(docBody(doc)).toBe('# Reader\n\nCode: `pages/ReaderPage.tsx`.\n');
  });

  it('takes its title from the first heading, else from its file name', () => {
    expect(docTitle(doc)).toBe('Reader');
    expect(docTitle(parseDoc('parked/experts-tracks.md', 'No heading.'))).toBe('experts-tracks');
  });

  it('lives at a studio URL by its place under docs/', () => {
    expect(['principles.md', 'decisions.md', 'system/components.md', 'system/motion.md', 'pages/post.md', 'parked/inbox.md']
      .map((path) => docHref(parseDoc(path, '')))).toEqual([
      '/design', '/design/decisions', '/design/components', '/design/system/motion', '/design/pages/post', '/design/parked/inbox',
    ]);
  });
});

describe('the rail', () => {
  const docs = [
    parseDoc('principles.md', '# Principles'),
    parseDoc('decisions.md', '# Decisions'),
    parseDoc('system/tokens.md', '# Tokens'),
    parseDoc('system/components.md', '# Component inventory'),
    parseDoc('pages/sources.md', '# Sources'),
    parseDoc('pages/reader.md', '# Reader'),
    parseDoc('pages/shell.md', '# Shell'),
    parseDoc('pages/post.md', '# Post'),
    parseDoc('parked/stories.md', '# Stories'),
    parseDoc('parked/inbox.md', '# Analyst inbox'),
  ];

  it('groups Studio, Pages (in reading order), Prototypes and Parked', () => {
    const groups = railGroups(docs, ['Button', 'Chip'], [{ id: '2026-10-10-title-wrap', label: 'title-wrap' }]);
    expect(groups.map((group) => [group.label, group.items.map((item) => [item.label, item.href])])).toEqual([
      ['Studio', [['Principles', '/design'], ['System', '/design/system'], ['Components', '/design/components'], ['Decisions', '/design/decisions']]],
      ['Pages', [['Reader', '/design/pages/reader'], ['Post', '/design/pages/post'], ['Sources', '/design/pages/sources'], ['Shell', '/design/pages/shell']]],
      ['Prototypes', [['title-wrap', '/design/prototypes/2026-10-10-title-wrap']]],
      ['Parked', [['Analyst inbox', '/design/parked/inbox'], ['Stories', '/design/parked/stories']]],
    ]);
  });

  it('nests the system docs under System and each primitive under Components', () => {
    const [studio] = railGroups(docs, ['Button', 'Chip'], []);
    const children = (label: string) => studio.items.find((item) => item.label === label)?.children?.map((child) => [child.label, child.href]);
    expect(children('System')).toEqual([['Tokens', '/design/system/tokens']]);
    expect(children('Components')).toEqual([['Button', '/design/components/Button'], ['Chip', '/design/components/Chip']]);
  });
});

describe('the real docs', () => {
  it('each have one studio URL, and the rail reaches every one', async () => {
    const { DOCS } = await import('./library');
    const hrefs = DOCS.map(docHref);
    expect(new Set(hrefs).size).toBe(DOCS.length);
    const reachable = railGroups(DOCS, [], []).flatMap((group) => group.items.flatMap((item) => [item, ...(item.children ?? [])]));
    expect(hrefs.filter((href) => !reachable.some((item) => item.href === href))).toEqual([]);
  });
});
