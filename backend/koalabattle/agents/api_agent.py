from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from time import perf_counter

from koalabattle.core.models import (
    AgentConfiguration,
    AgentDecision,
    AgentLifecycleState,
    AgentRequest,
    FallbackPolicy,
    FallbackRecord,
    ProviderErrorCategory,
    RetryAttempt,
    Side,
)
from koalabattle.core.pricing import PricingTable

from .base import Agent
from .providers import LLMProvider, ProviderError, ProviderRequest
from .validation import parse_structured_decision

StateCallback = Callable[
    [Side, AgentLifecycleState, int, dict[str, object]],
    Awaitable[None],
]


class AgentForfeitError(RuntimeError):
    pass


class MatchCostBudget:
    def __init__(self, limit: float | None) -> None:
        self.limit = limit
        self.spent = 0.0

    @property
    def exhausted(self) -> bool:
        return self.limit is not None and self.spent >= self.limit

    def add(self, amount: float) -> None:
        self.spent += amount


class ApiAgent:
    def __init__(
        self,
        provider: LLMProvider,
        model: str,
        configuration: AgentConfiguration,
        *,
        state_callback: StateCallback,
        pricing: PricingTable,
        manual_fallback: Agent | None = None,
        match_budget: MatchCostBudget | None = None,
        seed: int | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.configuration = configuration
        self._state_callback = state_callback
        self._pricing = pricing
        self._manual_fallback = manual_fallback
        self._match_budget = match_budget
        self._random = random.Random(seed)
        self._spent = 0.0

    async def decide(self, request: AgentRequest) -> AgentDecision:
        started_at = perf_counter()
        if (
            self.configuration.maximum_cost is not None
            and self._spent >= self.configuration.maximum_cost
        ):
            return await self._fallback(
                request, "Configured player cost limit reached", (), started_at=started_at
            )
        if self._match_budget is not None and self._match_budget.exhausted:
            return await self._fallback(
                request, "Configured match cost limit reached", (), started_at=started_at
            )
        legal_ids = {action.id for action in request.legal_actions}
        retries: list[RetryAttempt] = []
        prompt = request.prompt
        response = None
        await self._state_callback(request.side, AgentLifecycleState.THINKING, request.turn, {})
        for attempt in range(1, self.configuration.max_retries + 2):
            try:
                async with asyncio.timeout(self.configuration.timeout_seconds):
                    response = await self.provider.generate(
                        ProviderRequest(
                            prompt=prompt,
                            model=self.model,
                            timeout_seconds=self.configuration.timeout_seconds,
                            max_output_tokens=self.configuration.max_output_tokens,
                            temperature=(
                                self.configuration.temperature
                                if self.provider.capabilities.temperature
                                else None
                            ),
                            reasoning_effort=(
                                self.configuration.reasoning_effort
                                if self.provider.capabilities.reasoning_control
                                else None
                            ),
                        )
                    )
                parsed = parse_structured_decision(response.text, legal_ids)
                cost = self._pricing.estimate(self.provider.name, response.model, response.usage)
                if cost.available and cost.amount is not None:
                    self._spent += cost.amount
                    if self._match_budget is not None:
                        self._match_budget.add(cost.amount)
                decision = AgentDecision(
                    request_id=request.request_id,
                    match_id=request.match_id,
                    side=request.side,
                    turn=request.turn,
                    decision_sequence=request.decision_sequence,
                    action=parsed.action,
                    commentary=parsed.commentary,
                    raw_response=response.text,
                    provider_metadata={
                        "request_id": response.request_id,
                        "finish_reason": response.finish_reason,
                    },
                    latency_ms=round((perf_counter() - started_at) * 1000),
                    validation_attempts=attempt,
                    validation_errors=tuple(item.detail for item in retries),
                    provider=self.provider.name,
                    model=response.model,
                    usage=response.usage,
                    estimated_cost=cost,
                    retry_attempts=tuple(retries),
                )
                await self._state_callback(
                    request.side,
                    AgentLifecycleState.DECIDED,
                    request.turn,
                    {"action": decision.action, "commentary": decision.commentary},
                )
                return decision
            except TimeoutError as error:
                provider_error = ProviderError(
                    ProviderErrorCategory.TIMEOUT,
                    "Provider request timed out",
                    retryable=True,
                )
                provider_error.__cause__ = error
            except ProviderError as error:
                provider_error = error
            except ValueError as error:
                provider_error = ProviderError(
                    ProviderErrorCategory.INVALID_RESPONSE,
                    str(error),
                    retryable=True,
                )
            retries.append(
                RetryAttempt(
                    attempt=attempt,
                    category=provider_error.category,
                    detail=provider_error.detail,
                )
            )
            if attempt > self.configuration.max_retries or not provider_error.retryable:
                break
            await self._state_callback(
                request.side,
                AgentLifecycleState.RETRYING,
                request.turn,
                {"attempt": attempt + 1, "category": provider_error.category.value},
            )
            prompt = _repair_prompt(legal_ids, provider_error.detail)
            await asyncio.sleep(min(1.0, 0.2 * (2 ** (attempt - 1))))
        return await self._fallback(
            request,
            retries[-1].detail,
            tuple(retries),
            response=response,
            started_at=started_at,
        )

    async def _fallback(
        self,
        request: AgentRequest,
        reason: str,
        retries: tuple[RetryAttempt, ...],
        *,
        response: object | None = None,
        started_at: float,
    ) -> AgentDecision:
        await self._state_callback(
            request.side,
            AgentLifecycleState.ERROR,
            request.turn,
            {"category": retries[-1].category.value if retries else "cost_limit"},
        )
        record = FallbackRecord(policy=self.configuration.fallback, reason=reason)
        if self.configuration.fallback is FallbackPolicy.FORFEIT:
            raise AgentForfeitError(f"{self.provider.name} forfeited: {reason}")
        if self.configuration.fallback is FallbackPolicy.MANUAL:
            if self._manual_fallback is None:
                raise AgentForfeitError("manual fallback is unavailable")
            manual = await self._manual_fallback.decide(request)
            return manual.model_copy(
                update={
                    "provider": self.provider.name,
                    "model": self.model,
                    "retry_attempts": retries,
                    "fallback": record,
                    "validation_attempts": max(1, len(retries)),
                    "validation_errors": tuple(item.detail for item in retries),
                    "latency_ms": round((perf_counter() - started_at) * 1000),
                }
            )
        selected = self._random.choice(request.legal_actions)
        decision = AgentDecision(
            request_id=request.request_id,
            match_id=request.match_id,
            side=request.side,
            turn=request.turn,
            decision_sequence=request.decision_sequence,
            action=selected.id,
            commentary=f"Fallback selected {selected.name} after a provider problem.",
            provider=self.provider.name,
            model=self.model,
            retry_attempts=retries,
            fallback=record,
            error_category=retries[-1].category if retries else None,
            error_detail=reason,
            validation_attempts=max(1, len(retries)),
            validation_errors=tuple(item.detail for item in retries),
            latency_ms=round((perf_counter() - started_at) * 1000),
        )
        await self._state_callback(
            request.side,
            AgentLifecycleState.DECIDED,
            request.turn,
            {"action": decision.action, "fallback": True},
        )
        return decision


def _repair_prompt(legal_ids: set[str], detail: str) -> str:
    choices = "\n".join(f"- {item}" for item in sorted(legal_ids))
    return (
        f"Your previous response was invalid: {detail}\n"
        f"Choose exactly one of:\n{choices}\n"
        'Return JSON only: {"action":"<exact id>","commentary":"<brief public reason>"}'
    )
