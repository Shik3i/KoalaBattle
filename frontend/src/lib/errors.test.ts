import assert from 'node:assert/strict';
import test from 'node:test';

import { errorMessage } from './errors.ts';

test('an application error is shown as written', () => {
  assert.equal(errorMessage('team snapshot was not found', 422), 'team snapshot was not found');
});

test('a schema failure names the field instead of rendering as [object Object]', () => {
  const detail = [
    { loc: ['body', 'player1', 'team_snapshot_id'], msg: 'Input should be a valid UUID' }
  ];
  assert.equal(
    errorMessage(detail, 422),
    'player1.team_snapshot_id: Input should be a valid UUID'
  );
});

test('several schema failures are joined', () => {
  const detail = [
    { loc: ['body', 'limits', 'maximum_turns'], msg: 'Input should be greater than 0' },
    { loc: ['body', 'format'], msg: 'Field required' }
  ];
  assert.equal(
    errorMessage(detail, 422),
    'limits.maximum_turns: Input should be greater than 0; format: Field required'
  );
});

test('an unreadable body still reports the status', () => {
  assert.equal(errorMessage(undefined, 503), 'Request failed: 503');
  assert.equal(errorMessage([], 500), 'Request failed: 500');
  assert.equal(errorMessage('   ', 500), 'Request failed: 500');
});

test('a 401 points at the operator token instead of raw backend text', () => {
  // The backend's own wording ("missing or invalid bearer token") tells a user
  // nothing about where to fix it, and this is the one failure that is always
  // caused by the same missing setting.
  assert.match(errorMessage('missing or invalid bearer token', 401), /Operator access/);
  assert.match(errorMessage(undefined, 401), /Operator access/);
});
