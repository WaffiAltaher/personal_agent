# src/agent/memory/budget.py
"""
ContextBudgetManager — token-budget accounting for memory injection and reports.

Token estimation uses len(text)//4 (~4 characters per token).
Context clearing for the model happens in context_view.py; graph state is never trimmed.
"""

from agent.config import settings
from agent.memory.semantic import MemoryChunk


class ContextBudgetManager:
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


class TokenCounter:
    """Estimates token usage by message type and memory chunks."""

    def count_messages(self, messages: list) -> dict:
        """Break down token estimates by message type."""
        from langchain_core.messages import SystemMessage, ToolMessage

        system = conversation = tool_results = 0
        for msg in messages:
            tokens = len(str(msg.content)) // 4
            if isinstance(msg, SystemMessage):
                system += tokens
            elif isinstance(msg, ToolMessage):
                tool_results += tokens
            else:
                conversation += tokens
        total = system + conversation + tool_results
        return {
            "system": system,
            "conversation": conversation,
            "tool_results": tool_results,
            "total": total,
            "message_count": len(messages),
        }

    def count_memory_chunks(self, chunks: list) -> int:
        """Sum token estimates across all MemoryChunk content strings."""
        return sum(len(c.content) // 4 for c in chunks)

    def build_budget_report(self, messages: list, memory_chunks: list) -> str:
        """Format a human-readable context budget report."""
        cbm = ContextBudgetManager()
        counts = self.count_messages(messages)
        memory_tokens = self.count_memory_chunks(memory_chunks)
        total = counts["total"] + memory_tokens
        limit = settings.context_clear_threshold
        headroom = limit - total
        pct = (headroom / limit * 100) if limit else 0.0

        sep = "─" * 29
        return "\n".join([
            "=== Context Budget Report ===",
            f"System prompt:    {counts['system']:>8,} tokens",
            f"Conversation:     {counts['conversation']:>8,} tokens",
            f"Tool results:     {counts['tool_results']:>8,} tokens",
            f"Memory injection: {memory_tokens:>8,} tokens  (budget: {settings.memory_budget:,})",
            sep,
            f"Total (estimate): {total:>8,} tokens  (clear threshold: {limit:,})",
            f"Headroom:         {headroom:>8,} tokens  ({pct:.1f}%)",
        ])
