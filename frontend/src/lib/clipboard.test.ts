import test from 'node:test';
import assert from 'node:assert/strict';

import { writeToClipboard } from './clipboard.ts';

/** Minimal stand-in for the bits of `document` the execCommand path touches. */
function makeDocument(execResult: boolean) {
  const removed: unknown[] = [];
  const created: Array<Record<string, unknown>> = [];
  const doc = {
    execCommandCalls: [] as string[],
    removed,
    created,
    body: {
      appendChild(node: unknown) {
        return node;
      },
      removeChild(node: unknown) {
        removed.push(node);
        return node;
      },
    },
    createElement() {
      const node = {
        value: '',
        style: {} as Record<string, string>,
        setAttribute() {},
        select() {},
        setSelectionRange() {},
      };
      created.push(node);
      return node;
    },
    getSelection() {
      return { rangeCount: 0, removeAllRanges() {}, addRange() {} };
    },
    execCommand(command: string) {
      doc.execCommandCalls.push(command);
      return execResult;
    },
  };
  return doc;
}

test('uses the async clipboard API when it is available', async () => {
  const written: string[] = [];
  const navigatorRef = { clipboard: { writeText: async (text: string) => { written.push(text); } } };
  const doc = makeDocument(true);

  await writeToClipboard('hello', navigatorRef, doc as unknown as Document);

  assert.deepEqual(written, ['hello']);
  assert.deepEqual(doc.execCommandCalls, [], 'must not fall back when the API worked');
});

test('falls back to execCommand when navigator.clipboard is undefined', async () => {
  // This is the deployed instance: plain HTTP on a LAN address is not a secure context,
  // so the whole clipboard object is missing and reading .writeText off it throws.
  const doc = makeDocument(true);

  await writeToClipboard('hello', {}, doc as unknown as Document);

  assert.deepEqual(doc.execCommandCalls, ['copy']);
  assert.equal(doc.created[0].value, 'hello');
});

test('falls back when the async API exists but rejects', async () => {
  const navigatorRef = { clipboard: { writeText: async () => { throw new Error('denied'); } } };
  const doc = makeDocument(true);

  await writeToClipboard('hello', navigatorRef, doc as unknown as Document);

  assert.deepEqual(doc.execCommandCalls, ['copy'], 'a denied permission is still recoverable');
});

test('throws when both paths fail, so the caller can show an error', async () => {
  const doc = makeDocument(false);

  await assert.rejects(
    () => writeToClipboard('hello', {}, doc as unknown as Document),
    /Clipboard is unavailable/,
  );
});

test('always removes the temporary textarea, even when the copy fails', async () => {
  const doc = makeDocument(false);

  await assert.rejects(() => writeToClipboard('hello', {}, doc as unknown as Document));

  assert.equal(doc.removed.length, 1, 'a failed copy must not leak a node into the DOM');
});

test('throws rather than crashing when there is no document at all', async () => {
  await assert.rejects(
    () => writeToClipboard('hello', {}, undefined),
    /Clipboard is unavailable/,
  );
});
