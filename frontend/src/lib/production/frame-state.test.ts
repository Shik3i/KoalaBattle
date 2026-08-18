import assert from 'node:assert/strict';
import test from 'node:test';
import { createProductionFrameRenderer, renderAt } from './frame-state.ts';

const match = {
  id: '00000000-0000-0000-0000-000000000001',
  config: {
    format: 'gen9randombattle',
    generation: 9,
    players: [
      { side: 'p1', display_name: 'Alpha', agent_type: 'random' },
      { side: 'p2', display_name: 'Beta', agent_type: 'random' }
    ]
  },
  winner: 'p1',
  events: [
    { id: 1, match_id: 'm', sequence: 1, turn: 1, event_type: 'move_used', logical_offset_ms: 0, payload: { side: 'p1', move: 'Tackle' } },
    { id: 2, match_id: 'm', sequence: 2, turn: 2, event_type: 'battle_finished', logical_offset_ms: 0, payload: { result: { winner: 'p1', winner_name: 'Alpha' } } }
  ]
} as any;

const production = {
  duration_ms: 4000,
  cues: [
    { id: 'event-1-visual', track: 'visual', kind: 'move_used', start_ms: 1000, duration_ms: 500, event_sequence: 1, turn: 1, side: null, payload: {} },
    { id: 'event-2-visual', track: 'visual', kind: 'battle_finished', start_ms: 2000, duration_ms: 500, event_sequence: 2, turn: 2, side: null, payload: {} },
    { id: 'future-caption', track: 'captions', kind: 'agent-commentary', start_ms: 1800, duration_ms: 300, event_sequence: 2, turn: 2, side: 'p1', payload: { segments: [] } }
  ]
} as any;

test('renderAt never exposes future winner or event', () => {
  const early = renderAt(match, production, 1000);
  assert.equal(early.presentation.eventSequence, 1);
  assert.equal(early.presentation.finished, false);
  assert.equal(early.caption, null);
  assert.equal(early.commentary, null);
  const completed = renderAt(match, production, 2000);
  assert.equal(completed.presentation.finished, true);
  assert.equal(completed.presentation.winnerName, 'Alpha');
});

test('renderAt samples animation from logical time', () => {
  const frame = renderAt(match, production, 1250);
  assert.equal(frame.visualElapsedMs, 250);
  assert.equal(frame.visualProgress, 0.5);
});

test('instant state checkpoints apply before a same-time visible event', () => {
  const state = {
    match_id: 'm',
    turn: 1,
    perspective: 'p1',
    player: { side: 'p1', display_name: 'Alpha', active: null, team: [] },
    opponent: { side: 'p2', display_name: 'Beta', active: null, team: [] },
    weather: [],
    fields: [],
    last_action: null,
    public_history: [],
    result: null
  };
  const checkpointMatch = {
    ...match,
    events: [
      { ...match.events[0], sequence: 1, event_type: 'state_snapshot', payload: { state } },
      { ...match.events[0], sequence: 2, event_type: 'move_used', payload: { side: 'p1', move: 'Tackle' } }
    ]
  } as any;
  const checkpointProduction = {
    duration_ms: 2000,
    cues: [
      { id: 'event-2-visual', track: 'visual', kind: 'move_used', start_ms: 1000, duration_ms: 500, event_sequence: 2, turn: 1, payload: {} },
      { id: 'event-1-state', track: 'visual', kind: 'state_snapshot', start_ms: 1000, duration_ms: 0, event_sequence: 1, turn: 1, payload: {} }
    ]
  } as any;
  assert.equal(createProductionFrameRenderer(checkpointMatch, checkpointProduction).renderAt(1000).event?.sequence, 2);
});

test('renderAt keeps a 1500-event archive bounded by logical cue time', () => {
  const events = Array.from({ length: 1500 }, (_, index) => ({
    id: index + 1,
    match_id: 'large',
    sequence: index + 1,
    turn: index + 1,
    event_type: 'turn_started',
    logical_offset_ms: 0,
    payload: {}
  }));
  const cues = events.map((event) => ({
    id: `event-${event.sequence}-visual`,
    track: 'visual',
    kind: event.event_type,
    start_ms: event.sequence,
    duration_ms: 1,
    event_sequence: event.sequence,
    turn: event.turn,
    side: null,
    payload: {}
  }));
  const frame = renderAt(
    { ...match, id: 'large', winner: null, events } as any,
    { ...production, duration_ms: 1500, cues } as any,
    1000
  );
  assert.equal(frame.presentation.eventSequence, 1000);
  assert.equal(frame.presentation.finished, false);
  assert.equal(frame.visual?.event_sequence, 1000);
});

test('indexed renderer supports backward seeks without stale or future state', () => {
  const renderer = createProductionFrameRenderer(match, production);
  assert.equal(renderer.renderAt(2000).presentation.finished, true);
  const rewound = renderer.renderAt(1000);
  assert.equal(rewound.presentation.finished, false);
  assert.equal(rewound.event?.sequence, 1);
  assert.equal(renderer.renderAt(2000).event?.sequence, 2);
});

test('legacy productions derive duration from cues instead of freezing at frame zero', () => {
  const renderer = createProductionFrameRenderer(match, { ...production, duration_ms: 0 });
  const frame = renderer.renderAt(2000);
  assert.equal(frame.timeMs, 2000);
  assert.equal(frame.presentation.finished, true);
  assert.equal(frame.event?.sequence, 2);
});
