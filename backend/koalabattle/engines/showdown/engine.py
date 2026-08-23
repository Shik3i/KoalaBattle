from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from poke_env import AccountConfiguration, ServerConfiguration
from poke_env.battle import AbstractBattle, DoubleBattle, Pokemon
from poke_env.player import BattleOrder, Player
from poke_env.player.battle_order import DoubleBattleOrder, ForfeitBattleOrder

from koalabattle.agents import AgentForfeitError
from koalabattle.agents.base import Agent
from koalabattle.agents.context import PROMPT_SCHEMA_VERSION, PROMPT_TEMPLATE_VERSION
from koalabattle.core.models import AgentRequest, BattleResult, Side
from koalabattle.engines.base import BattleEngineContext, EngineOutcome
from koalabattle.events.protocol import normalize_showdown_message

from .context import PokemonShowdownContextProvider
from .mapper import action_to_order, battle_state, find_action, legal_actions

LOGGER = logging.getLogger(__name__)
MAX_NO_PROGRESS_SUBMISSIONS = 3


class NoProgressBattleError(RuntimeError):
    """Raised when Showdown keeps rejecting the same local action without progress."""


@dataclass
class DecisionSubmissionGuard:
    request_key: str | None = None
    progress_signature: str | None = None
    pending_action: str | None = None
    rejected_actions: set[str] = field(default_factory=set)
    submission_counts: dict[str, int] = field(default_factory=dict)
    retry_requested: bool = False

    def begin(self, request_key: str, progress_signature: str) -> bool:
        if request_key == self.request_key:
            if not self.retry_requested:
                return False
            self.retry_requested = False
            return True
        self.request_key = request_key
        self.progress_signature = progress_signature
        self.pending_action = None
        self.rejected_actions.clear()
        self.submission_counts.clear()
        self.retry_requested = False
        return True

    def register_submission(self, action: str) -> None:
        count = self.submission_counts.get(action, 0) + 1
        if count >= MAX_NO_PROGRESS_SUBMISSIONS:
            raise NoProgressBattleError(
                "Showdown made no authoritative progress after repeated "
                f"{action!r} submissions for request {self.request_key}"
            )
        self.submission_counts[action] = count
        self.pending_action = action

    def reject_pending(self) -> str | None:
        action = self.pending_action
        if action is not None:
            self.rejected_actions.add(action)
        self.retry_requested = True
        return action

    def is_current(self, request_key: str) -> bool:
        return request_key == self.request_key


def reconcile_duplicate_request_identities(
    battle: AbstractBattle, request: dict[str, Any]
) -> None:
    """Give duplicate species distinct objects before poke-env parses the request."""
    side = request.get("side")
    if not isinstance(side, dict):
        return
    requested = [item for item in side.get("pokemon", []) if isinstance(item, dict)]
    by_species: dict[str, list[dict[str, Any]]] = {}
    for item in requested:
        details = item.get("details")
        ident = item.get("ident")
        if not isinstance(details, str) or not isinstance(ident, str):
            continue
        by_species.setdefault(details.split(", ", 1)[0], []).append(item)
    team = battle._team  # noqa: SLF001 - poke-env has no identity-reconciliation API
    for species, duplicates in by_species.items():
        if len(duplicates) < 2 or all(item["ident"] in team for item in duplicates):
            continue
        for ident, pokemon in tuple(team.items()):
            if pokemon.identifies_as(species):
                del team[ident]
        for item in duplicates:
            ident = item["ident"]
            team[ident] = Pokemon(
                request_pokemon=item,
                name=ident.split(": ", 1)[-1],
                gen=battle.gen,
            )


async def _bridge(loop: asyncio.AbstractEventLoop, coroutine: Coroutine[Any, Any, Any]) -> Any:
    if asyncio.get_running_loop() is loop:
        return await coroutine
    future = asyncio.run_coroutine_threadsafe(coroutine, loop)
    return await asyncio.wrap_future(future)


class _KoalaPlayer(Player):
    def __init__(
        self,
        *,
        side: Side,
        agent: Agent,
        context: BattleEngineContext,
        app_loop: asyncio.AbstractEventLoop,
        server_configuration: ServerConfiguration,
        capture_protocol: bool,
    ) -> None:
        self.side = side
        self.agent = agent
        self.context = context
        self.app_loop = app_loop
        self.capture_protocol = capture_protocol
        self.decision_sequence = 0
        self.current_turn = 0
        self.limit_forfeit = False
        self.provider_forfeit = False
        self.terminal_error: NoProgressBattleError | None = None
        self.context_provider = PokemonShowdownContextProvider()
        self.strategy_memory: str | None = None
        self.submission_guard = DecisionSubmissionGuard()
        username = f"Koala{side.value.upper()}{str(context.match_id)[:7]}"
        super().__init__(
            account_configuration=AccountConfiguration(username, None),
            battle_format=context.config.format,
            max_concurrent_battles=1,
            save_replays=False,
            server_configuration=server_configuration,
            team=next(
                player.team_packed for player in context.config.players if player.side is side
            ),
        )

    @staticmethod
    def _request_key(battle: AbstractBattle) -> str:
        request = battle.last_request
        rqid = request.get("rqid")
        if rqid is not None:
            return f"{battle.battle_tag}:{rqid}"
        encoded = json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
        return f"{battle.battle_tag}:sha256:{hashlib.sha256(encoded).hexdigest()}"

    @staticmethod
    def _progress_signature(battle: AbstractBattle) -> str:
        request = battle.last_request
        side = request.get("side", {})
        pokemon = side.get("pokemon", []) if isinstance(side, dict) else []
        state = {
            "turn": battle.turn,
            "rqid": request.get("rqid"),
            "force_switch": request.get("forceSwitch"),
            "wait": request.get("wait", False),
            "pokemon": [
                {
                    "ident": item.get("ident"),
                    "active": item.get("active"),
                    "condition": item.get("condition"),
                }
                for item in pokemon
                if isinstance(item, dict)
            ],
        }
        return hashlib.sha256(
            json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    async def _handle_battle_request(
        self, battle: AbstractBattle, maybe_default_order: bool = False
    ) -> None:
        del maybe_default_order
        if battle.wait:
            self._waiting.set()  # noqa: SLF001
            return
        if battle.teampreview:
            await super()._handle_battle_request(battle)
            return
        request_key = self._request_key(battle)
        progress = self._progress_signature(battle)
        previous_key = self.submission_guard.request_key
        previous_action = self.submission_guard.pending_action
        if not self.submission_guard.begin(request_key, progress):
            return
        if previous_key is not None and previous_key != request_key and previous_action:
            await _bridge(
                self.app_loop,
                self.context.sink.emit(
                    "battle_action_acknowledged",
                    battle.turn,
                    {
                        "side": self.side.value,
                        "action": previous_action,
                        "request": previous_key,
                        "next_request": request_key,
                    },
                ),
            )
        try:
            choice = await self.choose_move(battle)
        except NoProgressBattleError as error:
            self.terminal_error = error
            await self.ps_client.send_message("/forfeit", battle.battle_tag)
            return
        if choice.message:
            await self.ps_client.send_message(choice.message, battle.battle_tag)

    @property
    def _display_names(self) -> dict[Side, str]:
        return {player.side: player.display_name for player in self.context.config.players}

    async def choose_move(self, battle: AbstractBattle) -> BattleOrder:
        maximum_turns = self.context.config.limits.maximum_turns
        if maximum_turns is not None and battle.turn > maximum_turns:
            self.limit_forfeit = True
            await _bridge(
                self.app_loop,
                self.context.sink.emit(
                    "match_limit_reached",
                    battle.turn,
                    {"side": self.side.value, "limit": "maximum_turns", "value": maximum_turns},
                ),
            )
            return ForfeitBattleOrder()
        if isinstance(battle, DoubleBattle):
            orders = DoubleBattleOrder.join_orders(*battle.valid_orders)
            if not self.context.config.allow_terastallization:
                orders = [
                    order
                    for order in orders
                    if not order.first_order.terastallize
                    and not order.second_order.terastallize
                ]
            if not orders:
                return self.choose_default_move()
            def doubles_power(order: DoubleBattleOrder) -> int:
                total = 0
                for choice in (order.first_order, order.second_order):
                    try:
                        power = getattr(choice.order, "base_power", 0)
                    except (KeyError, TypeError, ValueError):
                        power = 0
                    total += int(power) if isinstance(power, int | float) else 0
                return total

            selected_order = max(orders, key=doubles_power)
            self.decision_sequence += 1
            self.submission_guard.register_submission(selected_order.message)
            state = battle_state(
                battle,
                match_id=self.context.match_id,
                side=self.side,
                display_names=self._display_names,
            )
            await _bridge(
                self.app_loop,
                self.context.sink.emit(
                    "state_snapshot", battle.turn, {"state": state.model_dump(mode="json")}
                ),
            )
            await _bridge(
                self.app_loop,
                self.context.sink.emit(
                    "agent_decision",
                    battle.turn,
                    {
                        "side": self.side.value,
                        "action": selected_order.message,
                        "action_name": "Doubles turn",
                        "commentary": "",
                        "banter": "",
                        "public_text": "",
                        "provider": "local",
                        "model": "tactical-auto-doubles",
                        "latency_ms": 0,
                        "fallback": False,
                    },
                ),
            )
            return selected_order
        actions = legal_actions(battle)
        if not self.context.config.allow_terastallization:
            actions = tuple(action for action in actions if not action.terastallize)
        if not actions:
            return self.choose_default_move()
        actions = tuple(
            action
            for action in actions
            if action.id not in self.submission_guard.rejected_actions
        )
        if not actions:
            raise NoProgressBattleError(
                "Showdown rejected every legal action for authoritative request "
                f"{self.submission_guard.request_key}"
            )
        self.decision_sequence += 1
        state = battle_state(
            battle,
            match_id=self.context.match_id,
            side=self.side,
            display_names=self._display_names,
        )
        knowledge, context_snapshot, prompt, context_metrics = self.context_provider.build(
            state,
            actions,
            prompt_profile=self.context.config.prompt_profile,
            context_profile=self.context.config.context_profile,
            memory_policy=self.context.config.memory_policy,
            strategy_memory=self.strategy_memory,
            maximum_turns=self.context.config.limits.maximum_turns,
            banter_enabled=self.context.config.banter_enabled,
        )
        request = AgentRequest(
            request_id=uuid4(),
            match_id=self.context.match_id,
            side=self.side,
            turn=battle.turn,
            decision_sequence=self.decision_sequence,
            state=state,
            legal_actions=actions,
            prompt=prompt.combined,
            system_prompt=prompt.system,
            user_prompt=prompt.user,
            knowledge=knowledge,
            context=context_snapshot,
            context_metrics=context_metrics,
            prompt_profile_id=self.context.config.prompt_profile,
            prompt_profile_version=context_snapshot.prompt_profile_version,
            context_schema_version=context_snapshot.schema_version,
            knowledge_schema_version=knowledge.schema_version,
            history_policy_version=context_snapshot.history_policy_version,
            memory_policy=self.context.config.memory_policy,
            memory_policy_version=context_snapshot.memory_policy_version,
            prompt_schema_version=PROMPT_SCHEMA_VERSION,
            prompt_template_version=PROMPT_TEMPLATE_VERSION,
            banter_enabled=self.context.config.banter_enabled,
        )
        await _bridge(
            self.app_loop,
            self.context.sink.emit(
                "state_snapshot", battle.turn, {"state": state.model_dump(mode="json")}
            ),
        )
        try:
            decision = await _bridge(self.app_loop, self.agent.decide(request))
        except AgentForfeitError as error:
            self.provider_forfeit = True
            await _bridge(
                self.app_loop,
                self.context.sink.emit(
                    "agent_forfeit",
                    battle.turn,
                    {"side": self.side.value, "reason": str(error)},
                ),
            )
            return ForfeitBattleOrder()
        selected = find_action(decision.action, actions)
        if not self.submission_guard.is_current(self._request_key(battle)):
            raise NoProgressBattleError(
                "Discarded stale agent action after the authoritative Showdown request changed"
            )
        self.submission_guard.register_submission(decision.action)
        if self.context.config.memory_policy.value == "strategy-note":
            self.strategy_memory = decision.strategy_memory or self.strategy_memory
        else:
            self.strategy_memory = None
        await _bridge(self.app_loop, self.context.sink.record_decision(request, decision))
        await _bridge(
            self.app_loop,
            self.context.sink.emit(
                "agent_state",
                battle.turn,
                {"side": self.side.value, "state": "executing"},
            ),
        )
        await _bridge(
            self.app_loop,
            self.context.sink.emit(
                "agent_decision",
                battle.turn,
                {
                    "side": self.side.value,
                    "action": decision.action,
                    "action_name": selected.name,
                    "commentary": decision.commentary,
                    "banter": decision.banter,
                    "public_text": " ".join(
                        item for item in (decision.commentary, decision.banter) if item
                    ),
                    "provider": decision.provider,
                    "model": decision.model,
                    "latency_ms": decision.latency_ms,
                    "fallback": decision.fallback is not None,
                },
            ),
        )
        return action_to_order(selected, battle)

    async def _handle_battle_message(self, split_messages: list[list[str]]) -> None:
        request_parts = [
            parts
            for parts in split_messages[1:]
            if len(parts) >= 3 and parts[1] == "request" and parts[2]
        ]
        if request_parts:
            battle = await self._get_battle(split_messages[0][0])
            for parts in request_parts:
                request = json.loads(parts[2])
                if isinstance(request, dict):
                    reconcile_duplicate_request_identities(battle, request)
        for parts in split_messages[1:]:
            if len(parts) < 3 or parts[1] != "error":
                continue
            error = parts[2]
            if not error.startswith(("[Invalid choice]", "[Unavailable choice]")):
                continue
            rejected = self.submission_guard.reject_pending()
            await _bridge(
                self.app_loop,
                self.context.sink.emit(
                    "battle_action_rejected",
                    self.current_turn,
                    {
                        "side": self.side.value,
                        "action": rejected,
                        "request": self.submission_guard.request_key,
                        "error": error,
                    },
                ),
            )
        if self.capture_protocol:
            for parts in split_messages[1:]:
                normalized = normalize_showdown_message(parts)
                if normalized is None:
                    continue
                event_type, payload = normalized
                if event_type == "battle_started":
                    continue
                if event_type == "turn_started":
                    self.current_turn = int(payload.get("turn", self.current_turn))
                await _bridge(
                    self.app_loop,
                    self.context.sink.emit(event_type, self.current_turn, payload),
                )
        await super()._handle_battle_message(split_messages)


class ShowdownBattleEngine:
    name = "pokemon-showdown"
    version = "poke-env-adapter-v1"

    def __init__(self, websocket_url: str, authentication_url: str) -> None:
        self.server_configuration = ServerConfiguration(websocket_url, authentication_url)

    async def run(self, context: BattleEngineContext) -> EngineOutcome:
        app_loop = asyncio.get_running_loop()
        p1 = _KoalaPlayer(
            side=Side.P1,
            agent=context.agents[Side.P1],
            context=context,
            app_loop=app_loop,
            server_configuration=self.server_configuration,
            capture_protocol=True,
        )
        p2 = _KoalaPlayer(
            side=Side.P2,
            agent=context.agents[Side.P2],
            context=context,
            app_loop=app_loop,
            server_configuration=self.server_configuration,
            capture_protocol=False,
        )
        try:
            await p1.battle_against(p2, n_battles=1)
            terminal_error = p1.terminal_error or p2.terminal_error
            if terminal_error is not None:
                raise terminal_error
            if not p1.battles:
                raise RuntimeError("poke-env completed without exposing a battle")
            battle = next(reversed(p1.battles.values()))
            winner = Side.P1 if battle.won else Side.P2 if battle.lost else None
            winner_name = self._display_name(context, winner) if winner else None
            result = BattleResult(
                winner=winner,
                winner_name=winner_name,
                turns=battle.turn,
                reason=(
                    "maximum_turns"
                    if p1.limit_forfeit or p2.limit_forfeit
                    else "provider_forfeit"
                    if p1.provider_forfeit or p2.provider_forfeit
                    else "normal"
                    if winner
                    else "tie"
                ),
            )
            final_state = battle_state(
                battle,
                match_id=context.match_id,
                side=Side.P1,
                display_names={
                    player.side: player.display_name for player in context.config.players
                },
                result=result,
            )
            await context.sink.emit(
                "state_snapshot", battle.turn, {"state": final_state.model_dump(mode="json")}
            )
            raw_log = battle._build_replay_log()  # noqa: SLF001
            return EngineOutcome(result=result, raw_log=raw_log)
        finally:
            await asyncio.gather(
                p1.ps_client.stop_listening(),  # type: ignore[no-untyped-call]
                p2.ps_client.stop_listening(),  # type: ignore[no-untyped-call]
                return_exceptions=True,
            )

    @staticmethod
    def _display_name(context: BattleEngineContext, side: Side) -> str:
        return next(player.display_name for player in context.config.players if player.side is side)
