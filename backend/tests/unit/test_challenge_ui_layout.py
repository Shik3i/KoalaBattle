"""Structural guards for the Draft and battle-control game screens.

These assert the *hierarchy* the Draft pass established: the battle owns the top of the
control page, technical/streaming actions stay reachable but secondary, and the active
Draft run shows progress compactly instead of a statistics dashboard.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BATTLE_PAGE = ROOT / "frontend/src/routes/battle/[id]/+page.svelte"
CHALLENGE_PAGE = ROOT / "frontend/src/routes/challenges/[id]/+page.svelte"
NEW_RUN_PAGE = ROOT / "frontend/src/routes/challenges/new/+page.svelte"
CHALLENGE_LIST_PAGE = ROOT / "frontend/src/routes/challenges/+page.svelte"
CHALLENGE_HELPERS = ROOT / "frontend/src/lib/challenge.ts"
RENDERER_CARDS = ROOT / "frontend/src/lib/battle-renderer/RendererCards.svelte"
RENDERER_BROADCAST = ROOT / "frontend/src/lib/battle-renderer/RendererBroadcast.svelte"
RENDERER_COMMENTARY = ROOT / "frontend/src/lib/battle-renderer/RendererCommentary.svelte"
RENDERER = ROOT / "frontend/src/lib/BattleRenderer.svelte"
POKEMON_SPRITE = ROOT / "frontend/src/lib/PokemonSprite.svelte"
LAYOUT = ROOT / "frontend/src/routes/+layout.svelte"
APP_CSS = ROOT / "frontend/src/app.css"

TECHNICAL_ACTIONS = (
    "Open battle view",
    "Copy battle view URL",
    "Copy OBS URL",
    "Open OBS overlay",
)


def _markup(path: Path) -> str:
    source = path.read_text(encoding="utf-8")
    return source[source.index("</script>") : source.index("<style>")]


def _preview_section_start(markup: str) -> int:
    """Index of the renderer section, tolerant of extra attributes on the tag."""
    match = re.search(r'<section class="preview"[ >]', markup)
    assert match, "battle page no longer has a <section class=\"preview\"> block"
    return match.start()


def test_battle_renderer_is_the_first_block_and_the_identity_row_follows_it() -> None:
    markup = _markup(BATTLE_PAGE)

    preview = _preview_section_start(markup)
    head = markup.index('<div class="live-head">')
    # The battle (and its team bar) owns the top of the screen; the run's identity/
    # progress reads as a caption underneath it, not a bar pushing the arena down.
    assert preview < head
    # Nothing else may sit between the renderer and the identity row.
    between = markup[markup.index("</section>", preview) + len("</section>") : head]
    assert "<section" not in between, between
    assert "panel" not in between, between


def test_streaming_and_obs_actions_stay_available_inside_the_tools_menu() -> None:
    markup = _markup(BATTLE_PAGE)
    panel_start = markup.index('<div class="tool-menu-panel"')
    panel = markup[panel_start : markup.index("</details>", panel_start)]

    for action in TECHNICAL_ACTIONS:
        assert action in panel, action
        # And exactly once: no duplicate full-width bar reintroduced above the battle.
        assert markup.count(action) == 1, action
    assert 'class="view-bar' not in markup


def test_presentation_controls_are_collapsed_below_the_renderer() -> None:
    markup = _markup(BATTLE_PAGE)
    settings = markup.index('<details class="preview-settings">')
    tools = markup.index('<div class="preview-tools">')

    assert _preview_section_start(markup) < settings < tools
    assert "<summary>" in markup[settings:tools] or "<summary" in markup[settings:tools]


def test_game_screens_use_the_reduced_shell_padding() -> None:
    layout = LAYOUT.read_text(encoding="utf-8")
    css = APP_CSS.read_text(encoding="utf-8")

    assert "focus-route={focusRoute}" in layout
    assert "'/battle/'" in layout
    assert "challenges" in layout
    assert "main.focus-route" in css


def test_active_draft_run_shows_one_current_stage_and_no_statistics_dashboard() -> None:
    markup = _markup(CHALLENGE_PAGE)

    assert markup.count('id="current-stage"') == 1
    assert 'class="campaign-stats' not in markup
    # Record/battles/turns/drafted totals belong to the completion summary only.
    summary = markup[markup.index('id="summary"') :]
    for statistic in ("total_battles", "total_turns", "consumed_species_ids.length"):
        assert statistic in summary, statistic
        assert markup.count(statistic) == 1, statistic


def test_campaign_progress_is_a_compact_rail_and_history_is_collapsed() -> None:
    markup = _markup(CHALLENGE_PAGE)

    assert 'class="route-rail"' in markup
    assert 'class="route-entry" href={`/replay/${result.match_id}`}' in markup
    assert "<TrainerPortrait trainerId={stage.trainer_asset_id}" in markup
    assert 'class="stage-emblem"' in markup
    assert "attemptIndex + 1" in markup
    assert re.search(r'<details[^>]*class="battle-history[^"]*"', markup)
    history_tag = re.search(r'<details[^>]*class="battle-history[^"]*"[^>]*>', markup)
    assert history_tag and " open" not in history_tag.group(0)
    assert '<details class="run-details' in markup
    assert 'class="roster-strip"' in markup


def test_long_battle_audit_is_one_lazy_collapsed_drawer() -> None:
    markup = _markup(BATTLE_PAGE)

    assert (
        '<details bind:open={auditOpen} on:toggle={loadAuditArchive} '
        'class="battle-drawer audit-drawer panel">'
    ) in markup
    assert "getPresentationMatch(matchId)" in BATTLE_PAGE.read_text()
    assert "const archive = await getMatch(data.id)" in BATTLE_PAGE.read_text()
    lazy_guard = markup.index("{#if auditOpen}")
    decision_list = markup.index('<div class="decision-list">')
    assert lazy_guard < decision_list
    assert '<section class="audit-head">' not in markup
    assert "No decisions have been recorded yet." in markup


def test_draft_opponent_preview_is_collapsed_by_default() -> None:
    markup = _markup(CHALLENGE_PAGE)

    preview = re.search(r'<details[^>]*class="opponent-preview"[^>]*>', markup)
    assert preview and " open" not in preview.group(0)


def test_low_resolution_sprites_are_never_upscaled_beyond_two_times() -> None:
    sprite = POKEMON_SPRITE.read_text(encoding="utf-8")
    renderer = RENDERER.read_text(encoding="utf-8")

    assert "--natural-w" in sprite and "--natural-h" in sprite
    assert "calc(var(--natural-w,96) * 2px)" in sprite
    assert "calc(var(--natural-h,96) * 2px)" in sprite
    assert "const MAX_UPSCALE = 2;" in renderer


def test_new_run_page_offers_every_difficulty_with_its_exact_modifier() -> None:
    source = NEW_RUN_PAGE.read_text(encoding="utf-8")

    for identifier, detail in (
        ("normal", "Campaign levels"),
        ("hard", "Opponent +5 levels"),
        ("expert", "Opponent +10 levels"),
        ("nightmare", "Opponent +15 levels"),
    ):
        assert f"id: '{identifier}'" in source, identifier
        assert detail in source, detail
    assert "difficulty," in source
    assert "Opponent species and sets are identical on every difficulty" in source


def test_draft_quick_start_uses_the_shared_visible_standard_contract() -> None:
    page = CHALLENGE_LIST_PAGE.read_text(encoding="utf-8")
    setup = NEW_RUN_PAGE.read_text(encoding="utf-8")
    helpers = CHALLENGE_HELPERS.read_text(encoding="utf-8")

    assert "standardChallengePayload" in page
    assert "Fast Auto · Normal · Fast Watch" in page
    assert "STANDARD_CHALLENGE_SETTINGS" in setup
    assert "battleType: 'tactical-auto'" in helpers
    assert "battleExperience: 'fast-watch'" in helpers
    assert "difficulty: 'normal'" in helpers


def test_quick_start_waits_for_routes_but_not_the_full_run_history() -> None:
    page = CHALLENGE_LIST_PAGE.read_text(encoding="utf-8")

    assert "void loadHistory();" in page
    assert "void loadDefinitions();" in page
    assert "disabled={Boolean(quickStarting) || routesLoading}" in page
    assert "disabled={Boolean(quickStarting) || historyLoading}" not in page
    assert "definitions.length ? definitions : await loadDefinitions()" in page
    assert "routesError = caught instanceof Error" in page
    assert "historyError = caught instanceof Error" in page
    assert "Quick Draft Duo" in page
    assert "quickStart('doubles')" in page


def test_quick_draft_promises_automatic_matchup_selection() -> None:
    page = CHALLENGE_LIST_PAGE.read_text(encoding="utf-8")

    assert "Same team size · Auto matchup selection" in page
    assert "Even teams · Auto synergy selection" in page


def test_battle_heading_prioritizes_the_opponent_and_title() -> None:
    source = BATTLE_PAGE.read_text(encoding="utf-8")

    assert "campaignOpponentHeading(campaign)" in source
    assert "<h1 title={battleHeading}>{battleHeading}</h1>" in source


def test_battle_action_feed_uses_the_available_readable_space() -> None:
    source = RENDERER_COMMENTARY.read_text(encoding="utf-8")

    assert "width:clamp(300px,30cqw,440px)" in source
    assert "max-height:58%" in source
    assert "white-space:normal" in source
    assert "text-overflow:ellipsis" not in source


def test_both_pokemon_hp_plates_leave_room_for_names_and_types() -> None:
    source = RENDERER.read_text(encoding="utf-8")

    assert ".plate-far{top:5%;left:3.5%;width:clamp(320px,39cqw,500px)}" in source
    assert ".plate-near{bottom:6%;right:3.5%;width:clamp(320px,39cqw,500px)}" in source


def test_a_human_battler_cannot_pick_an_unattended_battle_experience() -> None:
    source = NEW_RUN_PAGE.read_text(encoding="utf-8")

    assert "playerIsInteractive = battleType === 'human'" in source
    assert (
        "if (playerIsInteractive && battleExperience !== 'normal') battleExperience = 'normal'"
        in source
    )
    assert source.count("disabled={playerIsInteractive}") == 2


def test_every_run_state_has_a_visible_state_and_a_way_forward() -> None:
    markup = _markup(CHALLENGE_PAGE)

    # `preparing` must never offer a launch button; the backend rejects it.
    hero = markup[markup.index('id="current-stage"') :]
    assert "run.status === 'preparing'" in hero
    assert hero.index("run.status === 'preparing'") < hero.index("class=\"button launch\"")
    # A persisted run error is shown instead of an unexplained Team review or dead page.
    assert 'class="run-error' in markup
    assert "{#if run.error &&" in markup
    # Failed and retired runs get an explicit ending with actions.
    assert "run.status === 'failed'" in markup
    assert "['cancelled','abandoned'].includes(run.status)" in markup
    assert "requestDeleteRun" in markup


def test_draft_page_guards_polling_races_and_first_load_navigation() -> None:
    source = CHALLENGE_PAGE.read_text(encoding="utf-8")
    script = source[: source.index("</script>")]

    # An out-of-order poll must not overwrite a newer mutation response.
    assert "viewSequence" in script
    assert "if (sequence !== viewSequence) return;" in script
    # The client fallback fires at most once per persisted deadline.
    assert "advancedDeadline !== current.auto_advance_at" in script
    # Landing on a run with a live match must not bounce the user out of the Draft map.
    assert "if (view && nextRun.active_match_id" in script


def test_spinning_reel_frames_are_hidden_from_assistive_technology() -> None:
    markup = _markup(CHALLENGE_PAGE)

    assert markup.count('class="reel-window" aria-hidden="true"') == 2
    assert 'class="visually-hidden" aria-live="polite"' in markup
    # The live region announces the settled result, never the spinning frames.
    assert 'aria-live="polite">Generation {generationRomanNumeral' in markup


def test_every_in_page_anchor_points_at_a_real_element() -> None:
    """Renaming a section must not silently break the buttons that jump to it."""
    for page in (CHALLENGE_PAGE, BATTLE_PAGE, NEW_RUN_PAGE):
        markup = _markup(page)
        targets = set(re.findall(r'id="([a-z][a-z0-9-]*)"', markup))
        anchors = set(re.findall(r'href="#([a-z][a-z0-9-]*)"', markup))
        # Anchors built in script (primaryHref) count too.
        script = page.read_text(encoding="utf-8")
        anchors |= set(re.findall(r"return '#([a-z][a-z0-9-]*)'", script))
        assert anchors <= targets, (page.name, sorted(anchors - targets))


def test_the_end_card_is_the_recap_and_nothing_paints_over_it() -> None:
    markup = _markup(RENDERER_CARDS)
    styles = RENDERER_CARDS.read_text(encoding="utf-8")

    # The separate opaque "FINAL" card used to cover the winner banner entirely.
    assert "director-result" not in markup
    assert 'class="recap"' in markup
    assert "winner-mvp" in markup
    # The banner must outrank the remaining full-screen director card.
    def layer(selector: str) -> int:
        match = re.search(rf"\{selector}\{{position:absolute;z-index:(\d+)", styles)
        assert match, selector
        return int(match.group(1))

    assert layer(".winner-banner") > layer(".director-card")


def test_the_campaign_result_uses_only_the_player_slot_for_p1() -> None:
    markup = _markup(RENDERER_CARDS)

    assert "!(campaign && presentation.winner === 'p1')" in markup
    provider = "{presentation.players[presentation.winner].providerLabel}"
    assert f"{{#if !campaign}}<em>{provider}</em>{{/if}}" in markup


def test_the_team_roster_bar_is_below_the_arena_and_contains_only_teams() -> None:
    renderer = _markup(RENDERER)
    broadcast = _markup(RENDERER_BROADCAST)

    assert renderer.index("<RendererBroadcast") > renderer.index("<RendererCommentary")
    assert "grid-template-rows:1fr auto" in RENDERER.read_text(encoding="utf-8")
    assert 'aria-label="Battle team rosters"' in broadcast
    assert broadcast.count('class="team-strip"') == 2
    for duplicate in ("player-name", "agent-state", "header-center", "KOALABATTLE"):
        assert duplicate not in broadcast


def test_doubles_near_side_hud_follows_the_same_left_to_right_slot_order_as_sprites() -> None:
    renderer = RENDERER.read_text(encoding="utf-8")

    assert ".doubles-layout .plate-near.field-slot-0{right:31.5%}" in renderer
    assert ".doubles-layout .plate-near.field-slot-1{right:2%}" in renderer
    assert ".doubles-layout .combatant-near.field-slot-0{left:7%}" in renderer
    assert ".doubles-layout .combatant-near.field-slot-1{left:30%}" in renderer


def test_the_campaign_intro_shows_the_trainer_and_both_levels() -> None:
    markup = _markup(RENDERER_CARDS)

    assert "trainerAssetUrl" in RENDERER_CARDS.read_text(encoding="utf-8")
    assert "versus-avatar" in markup
    assert "campaign.player_level" in markup
    assert "campaign.opponent_level" in markup
    assert "campaign.stage_index + 1" in markup


def test_every_renderer_surface_receives_the_campaign_badge() -> None:
    surfaces = ("battle", "watch", "replay", "overlay", "render")
    for surface in surfaces:
        page = ROOT / f"frontend/src/routes/{surface}/[id]/+page.svelte"
        source = page.read_text(encoding="utf-8")
        assert "campaign={match?.config.campaign || null}" in source, surface


def test_the_draft_shows_the_campaign_it_is_drafting_against() -> None:
    markup = _markup(CHALLENGE_PAGE)

    assert "campaign-preview" in markup
    assert "Who you will fight" in markup


def test_the_draft_header_is_only_the_generation_and_type_reels() -> None:
    """Everything else in that header duplicated the roster aside or the reroll buttons."""
    markup = _markup(CHALLENGE_PAGE)
    start = markup.index('<header class="roll-result">')
    header = markup[start : markup.index("</header>", start)]

    assert "draft-reels" in header
    assert "generation-reel" in header and "type-reel" in header
    for removed in ("Draft roll · Pick", "reroll-wallet", "pick-progress", "draft-guidance"):
        assert removed not in header, removed
    assert "draft-guidance" not in markup
    assert "reroll-wallet" not in markup
    assert "pick-progress" not in markup


def test_no_countdown_gates_the_next_stage() -> None:
    source = CHALLENGE_PAGE.read_text(encoding="utf-8")

    assert "autoCountdown" not in source
    assert "next-countdown" not in source
    # A short presentation-only transition announces the next opponent instead.
    assert "stage-transition" in source
    assert "STAGE_TRANSITION_MS" in source
    assert "prefers-reduced-motion: reduce" in source


def test_the_ai_drafter_acts_without_a_click_per_pick() -> None:
    source = CHALLENGE_PAGE.read_text(encoding="utf-8")

    assert "autoDraftedOffer" in source
    assert "void agentDraft();" in source
    # Manual escape hatches stay for a failed decision.
    assert "Retry AI decision" in source
    assert "Take over manually" in source


def test_training_rewards_are_gone_from_the_run_screen() -> None:
    source = CHALLENGE_PAGE.read_text(encoding="utf-8")

    for removed in ("pending_reward", "training_rewards", "claimReward", "reward-options"):
        assert removed not in source, removed


def test_the_roster_never_marks_pokemon_as_out_across_battles() -> None:
    source = CHALLENGE_PAGE.read_text(encoding="utf-8")
    markup = _markup(CHALLENGE_PAGE)

    assert "downed_entry_ids" not in source
    assert "class:downed" not in markup
    assert "stayed down" not in markup


def test_a_stopped_battle_says_so_next_to_the_arena() -> None:
    """A failed, cancelled or interrupted battle looks identical to one that is still
    thinking: the arena holds its last frame and the feed its last line. The only
    signals used to be a status pill and a collapsed drawer, both below the arena."""
    markup = _markup(BATTLE_PAGE)

    banner = markup.index('class="battle-stopped panel"')
    assert _preview_section_start(markup) < banner, "the notice belongs with the battle"
    assert "'failed','cancelled','interrupted'" in markup[:banner].split("{#if match &&")[-1]
    block = markup[banner : markup.index("</section>", banner)]
    # It has to be announced, and it has to offer the way out.
    open_tag = markup[markup.rindex("<section", 0, banner) : markup.index(">", banner)]
    assert 'role="alert"' in open_tag
    assert "handleResume" in block
    assert "handleRematch" in block
    assert "match.error" in block, "show what actually went wrong when the backend knows"
