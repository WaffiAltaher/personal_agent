# src/agent/memory/budget.py
"""
ContextBudgetManager — token-budget accounting for the agent's context window.

All limits are for Gemini 2.0 Flash (1M token window) with generous headroom.
Token estimation uses the fast len(text)//4 approximation (~4 chars per token).
This class is pure logic — it does not touch the graph or any external service.
Integration into the graph is deferred to a dedicated context-pressure session.
"""

from agent.memory.semantic import MemoryChunk


class ContextBudgetManager:
    # Configurable constants (override per-instance if needed)
    MAX_CONTEXT_TOKENS: int = 900_000
    SYSTEM_PROMPT_BUDGET: int = 2_000
    MEMORY_BUDGET: int = 10_000
    CONVERSATION_BUDGET: int = 50_000
    TOOL_RESULTS_BUDGET: int = 20_000

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Fast approximation: ~4 characters per token."""
        return len(text) // 4

    def trim_memory_results(
        self, chunks: list[MemoryChunk], budget: int
    ) -> list[MemoryChunk]:
        """
        Greedily include chunks from highest to lowest score until `budget`
        tokens is exhausted. Chunks that don't fit are dropped.
        """
        sorted_chunks = sorted(chunks, key=lambda c: c.score, reverse=True)
        result: list[MemoryChunk] = []
        used = 0
        for chunk in sorted_chunks:
            tokens = self.estimate_tokens(chunk.content)
            if used + tokens > budget:
                break
            result.append(chunk)
            used += tokens
        return result

    def trim_messages(self, messages: list, budget: int) -> list:
        """
        Keep the system message(s) plus the most recent non-system messages
        that fit within `budget` tokens. The system message is never dropped.
        """
        from langchain_core.messages import SystemMessage

        if not messages:
            return messages

        system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
        non_system = [m for m in messages if not isinstance(m, SystemMessage)]

        system_tokens = sum(
            self.estimate_tokens(str(m.content)) for m in system_msgs
        )
        remaining = budget - system_tokens

        # Walk backwards through non-system messages (most recent first)
        kept: list = []
        for msg in reversed(non_system):
            tokens = self.estimate_tokens(str(msg.content))
            if remaining - tokens < 0:
                break
            kept.append(msg)
            remaining -= tokens

        return system_msgs + list(reversed(kept))
