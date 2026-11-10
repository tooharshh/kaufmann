"""Bounded Gemini REST client; no local model or inference dependencies."""

import asyncio
import hashlib
import json
import math
import time
from collections import OrderedDict

import aiohttp

MODEL = "gemini-embedding-2"
PROFILE = "gemini-embedding-2:768:catalog-v1"
DIMENSIONS = 768
ENDPOINT = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:embedContent"
)


class EmbeddingUnavailable(Exception):
    pass


def document_text(row):
    # Never embed mutable price/stock, account details or invented product uses.
    fields = {
        key: row.get(key)
        for key in (
            "name_te",
            "product_category_tree",
            "description",
            "brand",
            "attributes",
            "product_specifications",
        )
    }
    body = json.dumps(fields, sort_keys=True, ensure_ascii=False, default=str)[:10000]
    return f"title: {str(row['product_name'])[:500]} | text: {body}"


def document_hash(row):
    return hashlib.sha256(document_text(row).encode()).hexdigest()


def vector_literal(values):
    if not isinstance(values, list) or len(values) != DIMENSIONS:
        raise EmbeddingUnavailable("invalid_dimensions")
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise EmbeddingUnavailable("invalid_vector")
    norm = math.sqrt(sum(v * v for v in values))
    if not math.isfinite(norm) or norm == 0:
        raise EmbeddingUnavailable("invalid_norm")
    return "[" + ",".join(str(v / norm) for v in values) + "]"


class GeminiEmbeddings:
    def __init__(self, http, api_key):
        self.http = http
        self.api_key = api_key
        self.cache = OrderedDict()
        self.lock = asyncio.Lock()
        self.retry_after = 0.0

    async def embed(self, text):
        try:
            async with self.http.post(
                ENDPOINT,
                headers={"x-goog-api-key": self.api_key},
                json={
                    "model": f"models/{MODEL}",
                    "content": {"parts": [{"text": text}]},
                    "outputDimensionality": DIMENSIONS,
                },
                timeout=aiohttp.ClientTimeout(total=3),
            ) as response:
                if response.status != 200:
                    raise EmbeddingUnavailable(f"provider_http_{response.status}")
                data = await response.json()
                return vector_literal(data["embedding"]["values"])
        except (
            aiohttp.ClientError,
            TimeoutError,
            ValueError,
            KeyError,
            TypeError,
        ) as exc:
            raise EmbeddingUnavailable("provider_unavailable") from exc

    async def query(self, text):
        # Hash cache keys so raw requests are not retained in cache keys/logs.
        key = hashlib.sha256(text.encode()).hexdigest()
        async with self.lock:
            now = time.monotonic()
            cached = self.cache.get(key)
            if cached and cached[0] > now:
                self.cache.move_to_end(key)
                return cached[1]
            if self.retry_after > now:
                raise EmbeddingUnavailable("provider_cooldown")
            try:
                result = await self.embed("task: search result | query: " + text)
            except EmbeddingUnavailable:
                self.retry_after = time.monotonic() + 30
                raise
            self.cache[key] = (now + 300, result)
            self.cache.move_to_end(key)
            while len(self.cache) > 128:
                self.cache.popitem(last=False)
            return result


def configured_embeddings(settings, http):
    if settings.values.get("SEMANTIC_SEARCH_ENABLED") != "true":
        return None
    return GeminiEmbeddings(http, settings["GEMINI_API_KEY"])
