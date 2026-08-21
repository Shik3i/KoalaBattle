'use strict';

exports.Formats = [
  {
    section: 'KoalaBattle',
    column: 4
  },
  {
    name: '[Gen 9] KoalaBattle Canonical NatDex Draft',
    desc: 'NatDex Draft with only clauses that reject sourced Red/Blue sets repealed.',
    mod: 'gen9',
    searchShow: false,
    tournamentShow: false,
    ruleset: [
      '[Gen 9] NatDex Draft',
      '!OHKO Clause',
      '!Evasion Abilities Clause',
      '!Evasion Moves Clause'
    ]
  }
];
