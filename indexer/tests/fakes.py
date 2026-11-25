"""In-memory stand-ins for the Chroma client and collection."""

from __future__ import annotations

import math
from typing import Any


def _match(meta: dict[str, Any], where: dict[str, Any] | None) -> bool:
    if not where:
        return True
    for key, cond in where.items():
        value = meta.get(key)
        if isinstance(cond, dict):
            if "$ne" in cond and value == cond["$ne"]:
                return False
        elif value != cond:
            return False
    return True


class FakeCollection:
    def __init__(self, name: str, metadata: dict[str, Any]) -> None:
        self.name, self.metadata, self.rows = name, dict(metadata), {}

    def add(self, ids, documents, embeddings, metadatas) -> None:  # type: ignore[no-untyped-def]
        self.upsert(ids, documents, embeddings, metadatas)

    def upsert(self, ids, documents, embeddings, metadatas) -> None:  # type: ignore[no-untyped-def]
        for i, d, e, m in zip(ids, documents, embeddings, metadatas):
            self.rows[i] = (d, list(e), dict(m))

    def update(self, ids, metadatas) -> None:  # type: ignore[no-untyped-def]
        for i, m in zip(ids, metadatas):
            d, e, _ = self.rows[i]
            self.rows[i] = (d, e, dict(m))

    def get(self, ids=None, where=None, include=None, limit=None, offset=0):  # type: ignore[no-untyped-def]
        keys = [i for i, (_, _, m) in self.rows.items()
                if (ids is None or i in ids) and _match(m, where)]
        if limit is not None:
            keys = keys[offset:offset + limit]
        out: dict[str, Any] = {"ids": keys}
        include = include or []
        if "metadatas" in include:
            out["metadatas"] = [self.rows[i][2] for i in keys]
        if "documents" in include:
            out["documents"] = [self.rows[i][0] for i in keys]
        if "embeddings" in include:
            out["embeddings"] = [self.rows[i][1] for i in keys]
        return out

    def delete(self, ids=None, where=None) -> None:  # type: ignore[no-untyped-def]
        doomed = [i for i, (_, _, m) in self.rows.items()
                  if (ids is None or i in ids) and _match(m, where)]
        for i in doomed:
            self.rows.pop(i, None)

    def query(self, query_embeddings, n_results=1, where=None, include=None):  # type: ignore[no-untyped-def]
        def cos(a: list[float], b: list[float]) -> float:
            na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
            return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0

        metas, dists, docs = [], [], []
        for q in query_embeddings:
            scored = sorted(((1.0 - cos(q, e), m, d) for _, (d, e, m) in self.rows.items()
                             if _match(m, where)), key=lambda t: t[0])[:n_results]
            metas.append([m for _, m, _ in scored])
            dists.append([x for x, _, _ in scored])
            docs.append([d for _, _, d in scored])
        return {"metadatas": metas, "distances": dists, "documents": docs}

    def modify(self, metadata=None, name=None) -> None:  # type: ignore[no-untyped-def]
        if metadata is not None:
            self.metadata = dict(metadata)

    def count(self) -> int:
        return len(self.rows)


class FakeClient:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}
        self.deleted: list[str] = []

    def heartbeat(self) -> int:
        return 1

    def get_collection(self, name: str) -> FakeCollection:
        if name not in self.collections:
            raise ValueError(f"Collection {name} does not exist")
        return self.collections[name]

    def delete_collection(self, name: str) -> None:
        if name not in self.collections:
            raise ValueError("no such collection")
        self.deleted.append(name)
        del self.collections[name]

    def create_collection(self, name: str, metadata: dict[str, Any]) -> FakeCollection:
        self.collections[name] = FakeCollection(name, metadata)
        return self.collections[name]
