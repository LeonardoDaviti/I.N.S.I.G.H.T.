import { test } from 'node:test';
import assert from 'node:assert/strict';

import { exportPath, formatBytes, formatDuration, newExportToken, restoreCommand } from './exportText.ts';

test('formatBytes: decimal units, one decimal under ten', () => {
  assert.equal(formatBytes(0), '0 bytes');
  assert.equal(formatBytes(999), '999 bytes');
  assert.equal(formatBytes(1_500), '1.5 KB');
  assert.equal(formatBytes(243_246_920), '243 MB');
  assert.equal(formatBytes(1_156_000_000), '1.2 GB');
});

test('formatDuration: seconds, then minutes', () => {
  assert.equal(formatDuration(1), 'about a second');
  assert.equal(formatDuration(25), 'about 25 seconds');
  assert.equal(formatDuration(150), 'about 3 minutes');
});

test('exportPath: logins only when asked', () => {
  assert.equal(exportPath('abc', false), '/api/export/everything?token=abc');
  assert.equal(exportPath('abc', true), '/api/export/everything?token=abc&logins=true');
});

test('newExportToken: 24 letters or digits, as the server accepts', () => {
  assert.match(newExportToken(), /^[a-z0-9]{24}$/);
  assert.equal(newExportToken(() => 0), 'a'.repeat(24));
});

test('restoreCommand: the file mounted, restored into a new database', () => {
  const command = restoreCommand('insight-2026-11-05-1200.zip');
  assert.ok(command.startsWith('docker compose run --rm -v "$PWD/insight-2026-11-05-1200.zip:/tmp/insight-2026-11-05-1200.zip:ro" backend'));
  assert.ok(command.endsWith('import_export.py /tmp/insight-2026-11-05-1200.zip --into insight_restored'));
});
