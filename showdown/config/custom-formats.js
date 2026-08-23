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
      // Only repeal the event/IV/gender/duplicate-move obtainability checks (the "Misc" bundle
      // member) for source-era normalization, per the format's own desc above. '!Obtainable'
      // (without "Misc") repeals the whole umbrella complex rule — Obtainable Moves, Obtainable
      // Abilities, Obtainable Formes, EV Limit = Auto, AND Obtainable Misc — which silently
      // disables move/ability/forme legality checking too. That broadening was an unintended
      // side effect of an unrelated commit (60beb1f, "add adaptive quick draft doubles"); revert
      // to the precisely-scoped rule.
      '!Obtainable Misc'
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
      // Same scoping as the singles format above: only repeal Obtainable Misc, not the whole
      // Obtainable umbrella rule.
      '!Obtainable Misc'
    ]
  }
];
