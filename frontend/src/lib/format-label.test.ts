import assert from 'node:assert/strict';
import test from 'node:test';
import { formatLabel, formatLabelShort } from './format-label.ts';

test('reads the formats this archive actually stores', () => {
  assert.equal(
    formatLabel('gen9koalabattlecanonicalnatdexdraft'),
    'Gen 9 KoalaBattle Canonical NatDex Draft'
  );
  assert.equal(
    formatLabel('gen9koalabattlecanonicalnatdexdraftdoubles'),
    'Gen 9 KoalaBattle Canonical NatDex Draft Doubles'
  );
  assert.equal(formatLabel('gen9natdexdraft'), 'Gen 9 NatDex Draft');
});

test('prefers the longest known term over a prefix of itself', () => {
  // "natdex" must not come back as "Nat" + "Dex", and "randombattle" is one term.
  assert.equal(formatLabel('gen1randombattle'), 'Gen 1 Random Battle');
  assert.equal(formatLabel('gen9nationaldexou'), 'Gen 9 National Dex OU');
});

test('keeps tiers uppercase and multi-word metagames spaced', () => {
  assert.equal(formatLabel('gen9ou'), 'Gen 9 OU');
  assert.equal(formatLabel('gen9anythinggoes'), 'Gen 9 Anything Goes');
  assert.equal(formatLabel('gen8balancedhackmons'), 'Gen 8 Balanced Hackmons');
});

test('passes through anything it cannot parse instead of mangling it', () => {
  assert.equal(formatLabel('somethingelse'), 'somethingelse');
  assert.equal(formatLabel(''), '');
  // An unknown run is preserved whole rather than guessed at: "cup" on its own is not
  // vocabulary here, so nothing in "wobbuffetcup" is split off.
  assert.equal(formatLabel('gen9wobbuffetcup'), 'Gen 9 wobbuffetcup');
  // A known term still separates cleanly from an unknown neighbour.
  assert.equal(formatLabel('gen9wobbuffetdoubles'), 'Gen 9 wobbuffet Doubles');
});

test('a bare generation stays a bare generation', () => {
  assert.equal(formatLabel('gen9'), 'Gen 9');
});

test('the short form drops the generation only', () => {
  assert.equal(formatLabelShort('gen9koalabattlecanonicalnatdexdraft'), 'KoalaBattle Canonical NatDex Draft');
  assert.equal(formatLabelShort('gen9'), 'Gen 9');
});
