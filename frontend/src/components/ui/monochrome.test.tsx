import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';

// Mark IX is monochrome (plan/INSIGHT_mark_ix_design.md). The Tailwind palette swap
// turns every colour class grey, but a literal hex in TS/TSX (an inline style, a
// `color: '#0EA5E9'` field) gets past it. This guard keeps them out.
const SRC = join(__dirname, '..', '..');
// The browser chrome colour must be a literal; it is the dark/light page background.
const ALLOW = new Set(['components/ThemeProvider.tsx']);

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

describe('monochrome guard', () => {
  it('has no literal hex colours in source outside the allowlist', () => {
    const offenders = sourceFiles(SRC)
      .map((path) => relative(SRC, path).split('\\').join('/'))
      .filter((rel) => !ALLOW.has(rel))
      .filter((rel) => /#[0-9a-fA-F]{6}\b/.test(readFileSync(join(SRC, rel), 'utf8')));
    expect(offenders).toEqual([]);
  });
});
