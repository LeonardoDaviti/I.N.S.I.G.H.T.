import { describe, expect, it } from 'vitest';

import { appRoutes, parseDoc, unclaimedRoutes } from './coverage';

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
