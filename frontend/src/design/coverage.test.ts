import { describe, expect, it } from 'vitest';

import {
  PAGE_SECTIONS, appRoutes, claimProblems, definedPrinciples, pageDocProblems, parseDoc, specimenProblems, unknownCitations, unclaimedRoutes,
} from './coverage';
import appSource from '../App.tsx?raw';
import { frameScenario } from './fixtures/scenarios';

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

describe('specimenProblems', () => {
  it('names a primitive with no specimen and a specimen whose primitive is gone', () => {
    const primitives = ['../components/ui/Button.tsx', '../components/ui/Chip.tsx', '../components/ui/ui.test.tsx'];
    const specimens = ['./specimens/components/Button.tsx', './specimens/components/Gone.tsx'];
    expect(specimenProblems(primitives, specimens)).toEqual([
      'components/ui/Chip.tsx has no specimen in src/design/specimens/components/Chip.tsx',
      'src/design/specimens/components/Gone.tsx shows a primitive components/ui no longer has',
    ]);
  });
});

/**
 * The real docs (D7.6). Loaded the way the studio will load them (D1), so a
 * doc that moves or is renamed here moves for /design too.
 */
const files = import.meta.glob<string>('./docs/**/*.md', { query: '?raw', import: 'default', eager: true });
const docs = Object.entries(files).map(([path, text]) => parseDoc(path.replace('./docs/', ''), text));
const pageDocs = docs.filter((doc) => doc.path.startsWith('pages/'));
const routes = appRoutes(appSource);

describe('the design docs', () => {
  it('find the routes in App.tsx', () => {
    expect(routes).toContain('/');
    expect(routes).toContain('/posts/:postId');
  });

  it('claim every route in App.tsx: as a page, a parked page or a redirect', () => {
    expect(unclaimedRoutes(routes, docs)).toEqual([]);
  });

  it('claim no route twice and no route App.tsx lacks', () => {
    expect(claimProblems(routes, docs)).toEqual([]);
  });

  it('cite only principles that exist', () => {
    expect(definedPrinciples(docs.find((doc) => doc.path === 'principles.md')!).size).toBeGreaterThan(0);
    expect(unknownCitations(docs)).toEqual([]);
  });

  it('keep at most 12 principles, numbered P1 up without gaps', () => {
    const numbers = [...definedPrinciples(docs.find((doc) => doc.path === 'principles.md')!)];
    expect(numbers.length).toBeLessThanOrEqual(12);
    expect(numbers).toEqual(numbers.map((_, index) => index + 1));
  });

  it('give every page doc the fixed template and its states', () => {
    expect(pageDocs.map((doc) => doc.path).sort()).toEqual(['pages/post.md', 'pages/reader.md', 'pages/shell.md', 'pages/sources.md']);
    expect(pageDocs.flatMap(pageDocProblems)).toEqual([]);
  });

  it('show every components/ui primitive as a hand-written specimen', () => {
    const primitives = Object.keys(import.meta.glob('../components/ui/*.tsx'));
    const specimens = Object.keys(import.meta.glob('./specimens/components/*.tsx'));
    expect(primitives.length).toBeGreaterThan(10);
    expect(specimenProblems(primitives, specimens)).toEqual([]);
  });

  it('have a fixture scenario for every state a page doc lists (D4, D7.6)', () => {
    const missing = pageDocs.flatMap((doc) => {
      const page = doc.path.replace(/^pages\//, '').replace(/\.md$/, '');
      return (doc.meta.states ?? [])
        .filter((state) => !frameScenario(page, state))
        .map((state) => `${page}/${state} has no frame scenario in design/fixtures/scenarios.ts`);
    });
    expect(missing).toEqual([]);
  });
});
