import { describe, expect, it } from 'vitest';

import {
  PAGE_SECTIONS, appRoutes, claimProblems, definedPrinciples, pageDocProblems, parseDoc, unknownCitations, unclaimedRoutes,
} from './coverage';

describe('appRoutes', () => {
  it('lists every <Route path> in the router source, in order', () => {
    const source = `
      <Routes>
        <Route path="/" element={<ReaderPage />} />
        <Route path="/read/:scopeKind/:scopeId?" element={<ReaderPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>`;
    expect(appRoutes(source)).toEqual(['/', '/read/:scopeKind/:scopeId?', '*']);
  });
});

describe('unclaimedRoutes', () => {
  it('names the routes no doc claims', () => {
    const docs = [
      parseDoc('pages/reader.md', '```meta\nkind: page\nroutes: /, /read/:scopeKind/:scopeId?\n```\n# Reader'),
      parseDoc('system/information-architecture.md', '```meta\nkind: system\nredirects: *\n```\n# IA'),
    ];
    expect(unclaimedRoutes(['/', '/read/:scopeKind/:scopeId?', '/new', '*'], docs)).toEqual(['/new']);
  });
});

describe('claimProblems', () => {
  it('flags a claim on a route App.tsx no longer has, and a route claimed twice', () => {
    const docs = [
      parseDoc('pages/reader.md', '```meta\nroutes: /, /gone\n```'),
      parseDoc('parked/inbox.md', '```meta\nroutes: /\n```'),
    ];
    expect(claimProblems(['/'], docs)).toEqual([
      'pages/reader.md claims /gone, which App.tsx does not have',
      '/ is claimed by more than one doc: pages/reader.md, parked/inbox.md',
    ]);
  });
});

describe('principle citations', () => {
  const principles = parseDoc('principles.md', '# Principles\n\n- **P1 Reading first.** One sentence.\n- **P2 Monochrome.** Another. See P1.\n');

  it('reads the defined principles from their bold labels, not from citations', () => {
    expect([...definedPrinciples(principles)]).toEqual([1, 2]);
  });

  it('flags a doc that cites a principle that does not exist', () => {
    const docs = [
      principles,
      parseDoc('pages/post.md', 'Centred column (P2). Icons only (P7, P1).'),
    ];
    expect(unknownCitations(docs)).toEqual(['pages/post.md cites P7, which principles.md does not define']);
  });
});

describe('pageDocProblems', () => {
  const complete = [
    '```meta\nkind: page\nroutes: /\nstates: normal, empty\n```',
    '# Reader',
    ...PAGE_SECTIONS.map((section) => `## ${section}\n\nText.`),
  ].join('\n\n');

  it('accepts a page doc with every template section and its states', () => {
    expect(pageDocProblems(parseDoc('pages/reader.md', complete))).toEqual([]);
  });

  it('names each missing template section', () => {
    const text = complete.replace('## Worst cases', '## Edge cases').replace('## Open issues', '## Later');
    expect(pageDocProblems(parseDoc('pages/reader.md', text))).toEqual([
      'pages/reader.md lacks the section "## Worst cases"',
      'pages/reader.md lacks the section "## Open issues"',
    ]);
  });

  it('wants the required states listed and the doc within 150 lines', () => {
    const text = complete.replace('states: normal, empty\n', '') + '\n'.repeat(150);
    expect(pageDocProblems(parseDoc('pages/reader.md', text))).toEqual([
      'pages/reader.md lists no `states:` in its meta block',
      `pages/reader.md is ${text.split('\n').length} lines; the limit is 150`,
    ]);
  });
});
