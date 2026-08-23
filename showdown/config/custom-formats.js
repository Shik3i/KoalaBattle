'use strict';

exports.Formats = [
  {
    section: 'KoalaBattle',
    column: 4
  },
  {
    name: '[Gen 9] KoalaBattle Canonical NatDex Draft',
    desc: 'NatDex Draft with source-era clauses and event minimum levels relaxed for fair campaign normalization.',
    mod: 'gen9',
    searchShow: false,
    tournamentShow: false,
    ruleset: [
      '[Gen 9] NatDex Draft',
      '!OHKO Clause',
      '!Evasion Abilities Clause',
      '!Evasion Moves Clause',
      '!Obtainable'
    ]
  },
  {
    name: '[Gen 9] KoalaBattle Canonical NatDex Draft Doubles',
    desc: 'Doubles variant of the canonical NatDex Draft campaign format.',
    mod: 'gen9',
    gameType: 'doubles',
    searchShow: false,
    tournamentShow: false,
    ruleset: [
      '[Gen 9] NatDex Draft',
      '!OHKO Clause',
      '!Evasion Abilities Clause',
      '!Evasion Moves Clause',
      '!Obtainable'
    ]
  }
];
