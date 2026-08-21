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


def test_battle_renderer_is_the_first_block_under_the_identity_row() -> None:
    markup = _markup(BATTLE_PAGE)

    head = markup.index('<div class="live-head">')
    preview = markup.index('<section class="preview">')
    assert head < preview
    # Nothing else may sit between the identity row and the renderer.
    between = markup[markup.index("</div>", markup.index("</details>", head)) : preview]
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

    assert markup.index('<section class="preview">') < settings < tools
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
    assert re.search(r'<details[^>]*class="battle-history[^"]*"', markup)
    assert '<details class="run-details' in markup
    assert 'class="roster-strip"' in markup


def test_new_run_page_offers_every_difficulty_with_its_exact_modifier() -> None:
    source = NEW_RUN_PAGE.read_text(encoding="utf-8")

    for identifier, detail in (
        ("normal", "Equal levels"),
        ("hard", "You −5 levels"),
        ("expert", "You −10 levels"),
        ("nightmare", "You −15 levels"),
    ):
        assert f"id: '{identifier}'" in source, identifier
        assert detail in source, detail
    assert "difficulty," in source
    assert "Opponent teams and levels are identical on every difficulty" in source


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
