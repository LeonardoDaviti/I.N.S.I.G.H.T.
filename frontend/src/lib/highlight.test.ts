import test from 'node:test';
import assert from 'node:assert/strict';

import { highlight, type Token } from './highlight.ts';

const kinds = (tokens: Token[]) => tokens.filter((t) => t.kind !== 'plain').map((t) => [t.kind, t.text]);

test('highlight python: keywords, the defined name, strings, decorators, constants and comments', () => {
  const tokens = highlight('@app.put("/x")\nasync def run(self):\n    return {"ok": True}  # done', 'python');
  assert.deepEqual(kinds(tokens), [
    ['decorator', '@app.put'],
    ['string', '"/x"'],
    ['keyword', 'async'],
    ['keyword', 'def'],
    ['name', 'run'],
    ['constant', 'self'],
    ['keyword', 'return'],
    ['string', '"ok"'],
    ['constant', 'True'],
    ['comment', '# done'],
  ]);
});

test('highlight python: a docstring is one string token, keywords inside it stay string', () => {
  assert.deepEqual(kinds(highlight('"""return if def"""', 'python')), [['string', '"""return if def"""']]);
});

test('highlight ts: template strings, comments and numbers', () => {
  assert.deepEqual(kinds(highlight('const n = 4; // four\nconst s = `a ${n}`;', 'ts')), [
    ['keyword', 'const'],
    ['number', '4'],
    ['comment', '// four'],
    ['keyword', 'const'],
    ['string', '`a ${n}`'],
  ]);
});

test('highlight dockerfile: the instruction at the start of a line is the keyword', () => {
  assert.deepEqual(kinds(highlight('RUN rm -rf fastapi\n# note', 'dockerfile')), [
    ['keyword', 'RUN'],
    ['comment', '# note'],
  ]);
});

test('highlight diff: whole lines are added or removed', () => {
  assert.deepEqual(kinds(highlight('-praw\n+telethon\n', 'diff')), [
    ['removed', '-praw\n'],
    ['added', '+telethon\n'],
  ]);
});

test('highlight never loses or reorders a character', () => {
  const source = 'def f(x):\n    """doc"""\n    return x + 1  # one\n';
  for (const lang of ['python', 'ts', 'dockerfile', 'diff', 'comment', 'text'] as const) {
    assert.equal(highlight(source, lang).map((t) => t.text).join(''), source);
  }
});
