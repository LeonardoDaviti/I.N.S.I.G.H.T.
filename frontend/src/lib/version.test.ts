import test from 'node:test';
import assert from 'node:assert/strict';

import { versionLine } from './version.ts';

const web = { version: 'Mark IX v9.1', commit: 'b9fcc6e', commit_date: '2026-10-27' };
const dev = { version: null, commit: null, commit_date: null };

test('in sync: the version, commit and commit date', () => {
  assert.equal(versionLine(web, { ...web }), 'I.N.S.I.G.H.T. Mark IX v9.1 · b9fcc6e · 27 Oct 2026');
});

test('before the API answers, or when it cannot, the web build alone', () => {
  assert.equal(versionLine(web, undefined), 'I.N.S.I.G.H.T. Mark IX v9.1 · b9fcc6e · 27 Oct 2026');
});

test('out of step: both builds, plainly', () => {
  const api = { version: 'Mark IX v9.0', commit: '0b1458d', commit_date: '2026-10-11' };
  assert.equal(versionLine(web, api), 'I.N.S.I.G.H.T. Mark IX · Web v9.1 · b9fcc6e · API v9.0 · 0b1458d, out of step');
  assert.equal(versionLine(web, { ...web, commit: '0b1458d' }),
    'I.N.S.I.G.H.T. Mark IX · Web v9.1 · b9fcc6e · API v9.1 · 0b1458d, out of step');
  assert.equal(versionLine(web, { ...api, version: 'Mark X v10.0' }),
    'I.N.S.I.G.H.T. Web Mark IX v9.1 · b9fcc6e · API Mark X v10.0 · 0b1458d, out of step');
});

test('dev build: no stamp says so', () => {
  assert.equal(versionLine(dev, { ...dev }), 'I.N.S.I.G.H.T. dev build');
  assert.equal(versionLine(dev, undefined), 'I.N.S.I.G.H.T. dev build');
  assert.equal(versionLine(dev, web), 'I.N.S.I.G.H.T. Web dev build · API Mark IX v9.1 · b9fcc6e, out of step');
});

test('a malformed commit date is left out', () => {
  assert.equal(versionLine({ ...web, commit_date: 'soon' }, undefined), 'I.N.S.I.G.H.T. Mark IX v9.1 · b9fcc6e');
});
