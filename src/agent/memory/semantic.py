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

COSINE_COLLECTION_METADATA = {"hnsw:space": "cosine"}


@dataclass
class MemoryChunk:
    content: str
    source: str       # "documents" or "memories"
    score: float
    metadata: dict = field(default_factory=dict)


def _collection_uses_cosine(store: Chroma) -> bool:
    return store._collection.configuration.get("hnsw", {}).get("space") == "cosine"


class SemanticMemory:
    def __init__(self, persist_dir: str | None = None):
        path = str(Path(persist_dir or settings.chroma_path))
        Path(path).mkdir(parents=True, exist_ok=True)
        self._persist_dir = path

        self._embeddings = GoogleGenerativeAIEmbeddings(
            model=settings.chroma_embedding_model,
            google_api_key=settings.google_api_key,
        )

        self._documents = self._open_collection("documents")
        self._memories = self._open_collection("memories")

        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=500, chunk_overlap=50
        )

    def _open_collection(self, name: str) -> Chroma:
        store = Chroma(
            collection_name=name,
            embedding_function=self._embeddings,
            persist_directory=self._persist_dir,
            collection_metadata=COSINE_COLLECTION_METADATA,
        )
        if not _collection_uses_cosine(store):
            return self._reindex_collection(name)
        return store

    def _reindex_collection(self, name: str) -> Chroma:
        """One-off migration: rebuild a legacy L2 collection in cosine space."""
        legacy = Chroma(
            collection_name=name,
            embedding_function=self._embeddings,
            persist_directory=self._persist_dir,
        )
        payload = legacy.get(include=["documents", "metadatas"])
        ids = payload["ids"]
        texts = payload["documents"]
        metadatas = payload["metadatas"]
        legacy._client.delete_collection(name)
        store = Chroma(
            collection_name=name,
            embedding_function=self._embeddings,
            persist_directory=self._persist_dir,
            collection_metadata=COSINE_COLLECTION_METADATA,
        )
        if texts:
            store.add_texts(texts=texts, metadatas=metadatas, ids=ids)
        return store

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

    def search_documents(self, query: str, k: int = 5) -> list[MemoryChunk]:
        threshold = settings.memory_score_threshold
        results = self._documents.similarity_search_with_relevance_scores(query, k=k)
        return [
            MemoryChunk(
                content=doc.page_content,
                source="documents",
                score=score,
                metadata=doc.metadata,
            )
            for doc, score in results
            if score >= threshold
        ]

    def search_memories(self, query: str, k: int = 3) -> list[MemoryChunk]:
        threshold = settings.memory_score_threshold
        results = self._memories.similarity_search_with_relevance_scores(query, k=k)
        return [
            MemoryChunk(
                content=doc.page_content,
                source="memories",
                score=score,
                metadata=doc.metadata,
            )
            for doc, score in results
            if score >= threshold
        ]

    def search_all(self, query: str, k: int = 5) -> list[MemoryChunk]:
        """Search both collections, deduplicate by content, rank by score."""
        doc_results = self.search_documents(query, k=k)
        memory_results = self.search_memories(query, k=k)

        seen: set[str] = set()
        combined: list[MemoryChunk] = []
        for chunk in sorted(
            doc_results + memory_results, key=lambda c: c.score, reverse=True
        ):
            if chunk.content not in seen:
                seen.add(chunk.content)
                combined.append(chunk)

        return combined[:k]
