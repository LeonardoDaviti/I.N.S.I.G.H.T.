import test from 'node:test';
import assert from 'node:assert/strict';

import { parseAnalysisFlag } from './features.ts';

test('parseAnalysisFlag accepts the same truthy words as the backend', () => {
  for (const raw of ['on', 'true', '1', 'yes', ' ON ', 'True']) assert.equal(parseAnalysisFlag(raw), true, raw);
  for (const raw of [undefined, '', 'off', 'false', '0', 'no', 'maybe']) assert.equal(parseAnalysisFlag(raw), false, String(raw));
});
