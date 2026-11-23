import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';

// nginx's CSP lets only this build's scripts run (0187); index.html's one inline script runs by its hash: change
// the script and this fails until nginx.conf has the new hash (a stale one would silently bring back the dark flash).
const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8');
const html = read('../../index.html');
const nginx = read('../../nginx.conf');
const policy = /add_header Content-Security-Policy "([^"]+)" always;/.exec(nginx)?.[1] ?? '';

test('every inline script of index.html is allowed by its hash, and nothing else inline', () => {
  const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
  assert.ok(inline.length > 0);
  const scriptSrc = /script-src ([^;]+)/.exec(policy)?.[1] ?? '';
  for (const body of inline) {
    const hash = createHash('sha256').update(body, 'utf8').digest('base64');
    assert.ok(scriptSrc.includes(`'sha256-${hash}'`), `index.html's inline script is not in nginx.conf: 'sha256-${hash}'`);
  }
  assert.ok(!scriptSrc.includes("'unsafe-inline'") && !scriptSrc.includes("'unsafe-eval'"));
});

test('no plugins, no <base>, no framing by other sites', () => {
  for (const directive of ["object-src 'none'", "base-uri 'self'", "frame-ancestors 'self'", "default-src 'self'"]) {
    assert.ok(policy.includes(directive), directive);
  }
});
