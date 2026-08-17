from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any
from uuid import uuid4

from poke_env import AccountConfiguration, ServerConfiguration
from poke_env.battle import AbstractBattle
from poke_env.player import BattleOrder, Player
from poke_env.player.battle_order import ForfeitBattleOrder

from koalabattle.agents import AgentForfeitError
from koalabattle.agents.base import Agent
from koalabattle.agents.context import PROMPT_SCHEMA_VERSION, PROMPT_TEMPLATE_VERSION
from koalabattle.core.models import AgentRequest, BattleResult, Side
from koalabattle.engines.base import BattleEngineContext, EngineOutcome
from koalabattle.events.protocol import normalize_showdown_message

from .context import PokemonShowdownContextProvider
from .mapper import action_to_order, battle_state, find_action, legal_actions

LOGGER = logging.getLogger(__name__)


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
        self.context_provider = PokemonShowdownContextProvider()
        self.strategy_memory: str | None = None
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
        actions = legal_actions(battle)
        if not actions:
            return self.choose_default_move()
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
                    "provider": decision.provider,
                    "model": decision.model,
                    "latency_ms": decision.latency_ms,
                    "fallback": decision.fallback is not None,
                },
            ),
        )
        return action_to_order(selected, battle)

    async def _handle_battle_message(self, split_messages: list[list[str]]) -> None:
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
