# src/agent/memory/semantic.py
"""
Semantic memory — embeds and stores text in Chroma so the agent can
retrieve relevant context from approved memories and ingested documents.

Two collections:
  - `documents` : files/pages the user explicitly ingests
  - `memories`  : facts stored via the approved `remember` tool
"""

import uuid
from dataclasses import dataclass, field
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from agent.config import settings


@dataclass
class MemoryChunk:
    content: str
    source: str       # "documents" or "memories"
    score: float
    metadata: dict = field(default_factory=dict)


class SemanticMemory:
    def __init__(self, persist_dir: str | None = None):
        path = str(Path(persist_dir or settings.chroma_path))
        Path(path).mkdir(parents=True, exist_ok=True)

        self._embeddings = GoogleGenerativeAIEmbeddings(
            model=settings.chroma_embedding_model,
            google_api_key=settings.google_api_key,
        )

        self._documents = Chroma(
            collection_name="documents",
            embedding_function=self._embeddings,
            persist_directory=path,
        )
        self._memories = Chroma(
            collection_name="memories",
            embedding_function=self._embeddings,
            persist_directory=path,
        )

        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=500, chunk_overlap=50
        )

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def ingest_document(self, text: str, metadata: dict) -> str:
        """Chunk, embed, and store a document. Returns the doc_id."""
        doc_id = str(uuid.uuid4())
        chunks = self._splitter.split_text(text)
        ids = [f"{doc_id}_{i}" for i in range(len(chunks))]
        metadatas = [
            {**metadata, "doc_id": doc_id, "chunk_index": i}
            for i in range(len(chunks))
        ]
        self._documents.add_texts(texts=chunks, metadatas=metadatas, ids=ids)
        return doc_id

    def remember(self, text: str) -> str:
        """Store one approved long-term memory. Returns the memory id."""
        memory_id = str(uuid.uuid4())
        self._memories.add_texts(
            texts=[text],
            metadatas=[{"memory_id": memory_id}],
            ids=[memory_id],
        )
        return memory_id

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def search_documents(
        self, query: str, k: int = 5, score_threshold: float = 0.7
    ) -> list[MemoryChunk]:
        results = self._documents.similarity_search_with_relevance_scores(query, k=k)
        return [
            MemoryChunk(
                content=doc.page_content,
                source="documents",
                score=score,
                metadata=doc.metadata,
            )
            for doc, score in results
            if score >= score_threshold
        ]

    def search_memories(
        self, query: str, k: int = 3, score_threshold: float = 0.7
    ) -> list[MemoryChunk]:
        results = self._memories.similarity_search_with_relevance_scores(query, k=k)
        return [
            MemoryChunk(
                content=doc.page_content,
                source="memories",
                score=score,
                metadata=doc.metadata,
            )
            for doc, score in results
            if score >= score_threshold
        ]

    def search_all(self, query: str, k: int = 5) -> list[MemoryChunk]:
        """Search both collections, deduplicate by content, rank by score."""
        threshold = settings.memory_score_threshold
        doc_results = self.search_documents(query, k=k, score_threshold=threshold)
        memory_results = self.search_memories(query, k=k, score_threshold=threshold)

        seen: set[str] = set()
        combined: list[MemoryChunk] = []
        for chunk in sorted(
            doc_results + memory_results, key=lambda c: c.score, reverse=True
        ):
            if chunk.content not in seen:
                seen.add(chunk.content)
                combined.append(chunk)

        return combined[:k]
