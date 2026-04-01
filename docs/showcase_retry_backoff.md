# CAM Showcase: Retry with Backoff

## What This Demonstrates

CAM (Claw Autonomous Miner) mines patterns from real codebases and stores
them as searchable knowledge.  When a new task arrives, CAM retrieves
relevant patterns and injects them into the AI agent's prompt — so the agent
writes code informed by **proven implementations**, not just its training
data.

This showcase runs the same task twice:

| Run | Knowledge Base | What the agent sees |
|-----|---------------|---------------------|
| **A — Base** | Empty (no mined knowledge) | Only the task description |
| **B — KB-equipped** | 2,895 methodologies mined from 250+ repos | Task description **+ 5 retrieved retry/backoff patterns** with real code |

The task: *"Add retry logic with exponential backoff to this API client."*

---

## The Target Code (Both Runs Start Here)

```python
# weather_client.py — a bare API client with no retry logic

import httpx

BASE_URL = "https://api.weather.example.com/v1"

def get_forecast(city: str) -> dict:
    """Fetch a 5-day forecast for the given city."""
    resp = httpx.get(f"{BASE_URL}/forecast", params={"city": city})
    resp.raise_for_status()
    return resp.json()

def get_alerts(region: str) -> list[dict]:
    """Fetch active weather alerts for a region."""
    resp = httpx.get(f"{BASE_URL}/alerts", params={"region": region})
    resp.raise_for_status()
    return resp.json()["alerts"]
```

The problem: any transient network failure, rate limit (HTTP 429), or server
error (5xx) crashes the caller immediately.

---

## What Happens When CAM Searches Its Knowledge Base

When the task arrives, CAM's hybrid search engine (vector similarity + BM25
text ranking) queries 2,895 stored methodologies and retrieves the top 5
matches in **1.4 seconds**.  These are the actual results from a live run:

| # | Pattern | Mined From | Relevance | Domain |
|---|---------|-----------|-----------|--------|
| 1 | Retry logic with exponential backoff for external APIs | MiroFish | 0.557 | code_quality, error_handling, api_design |
| 2 | Safe LLM call wrapper with retry/backoff and provider setup | agents | 0.549 | code_quality, api_design, error_handling |
| 3 | Retry policy with bounded exponential backoff | claw-code | 0.548 | code_quality, error_handling, devops |
| 4 | Graceful retry policy with explicit non-retryable classification | meta-harness-tbench2 | 0.548 | code_quality, error_handling, api_design |
| 5 | Standalone retry decorator module | (prior CAM task) | 0.527 | testing, error_handling |

Each pattern carries full implementation code, domain tags, activation
triggers, and an implementation sketch — all extracted from the original
source code during mining.

### What the patterns teach (plain English)

**Pattern 1 (MiroFish)** — Wrap external API calls with retry logic that
uses exponential backoff. Separate the retry concern from the business logic.

**Pattern 2 (agents)** — LLM provider calls need a safe wrapper that retries
transient failures and initializes provider state before the first call.

**Pattern 3 (claw-code)** — Retry only retryable failures. Use a bounded
exponential backoff that saturates at a maximum delay. Preserve the last
error so callers get a clear terminal failure message.

**Pattern 4 (meta-harness)** — Explicitly classify which errors are
retryable and which are not.  Non-retryable errors (400, 404) should fail
fast without wasting retry budget.

---

## How CAM Injects This Into the Agent's Prompt

CAM builds two sections that the AI agent reads before writing any code:

```
## Hints from Past Solutions
- Similar past solution: CLAW currently has basic error handling but lacks
  sophisticated retry logic for external services.
- Similar past solution: This pattern adds a robust, centralized retry
  boundary for transient provider failures.
- Similar past solution: Provider adapters and remote operations could
  benefit from an explicit bounded retry primitive.
- Similar past solution: A consistent retry contract around model errors
  would improve resilience and debuggability.

## Knowledge Base (HybridSearch results)

### Pattern: Retry logic with exponential backoff for external APIs
Source: source:MiroFish
Domain: code_quality, error_handling, api_design
[Full methodology with implementation code]

### Pattern: Retry policy with bounded exponential backoff
Source: source:claw-code
Domain: code_quality, error_handling, devops, api_design, performance
[Full methodology with implementation code]

### Pattern: Graceful retry policy with explicit non-retryable classification
Source: source:meta-harness-tbench2-artifact
Domain: code_quality, error_handling, api_design, llm_integration
[Full methodology with implementation code]
```

The agent reads all of this as context before it writes a single line.

---

## Run A — Base CAM (empty knowledge base)

The agent has no mined patterns. It uses only its training data.
A typical output looks like this:

```python
import httpx
import time

BASE_URL = "https://api.weather.example.com/v1"

def get_forecast(city: str, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            resp = httpx.get(f"{BASE_URL}/forecast", params={"city": city})
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise

def get_alerts(region: str, retries: int = 3) -> list[dict]:
    for attempt in range(retries):
        try:
            resp = httpx.get(f"{BASE_URL}/alerts", params={"region": region})
            resp.raise_for_status()
            return resp.json()["alerts"]
        except httpx.HTTPError:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise
```

**What's wrong with this:**

- **Retries ALL errors** — A 400 Bad Request or 404 Not Found will never
  succeed on retry. The code wastes time retrying them anyway.
- **No max delay cap** — At attempt 10, the delay is `2^10` = 1,024
  seconds (17 minutes). Nothing stops it.
- **No jitter** — If 100 clients hit a rate limit at the same time, they
  all retry at the exact same moment. This is called "thundering herd" and
  it makes the problem worse.
- **No 429 Retry-After** — When the server says "slow down" and tells you
  exactly how long to wait (via the `Retry-After` header), this code
  ignores it.
- **Copy-pasted** — The retry logic is duplicated in every function. Adding
  a third endpoint means copy-pasting it again.
- **No error context** — When all retries fail, you don't know how many
  were attempted or what the progression looked like.

---

## Run B — KB-Equipped CAM (2,895 mined methodologies)

The agent has 5 retrieved patterns in its context. The patterns from
MiroFish, claw-code, agents, and meta-harness all point to the same set of
best practices. Expected output:

```python
import httpx
import time
import random
import logging
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

BASE_URL = "https://api.weather.example.com/v1"

T = TypeVar("T")

# Status codes that are safe to retry
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class RetriesExhausted(Exception):
    """All retry attempts failed."""
    def __init__(self, attempts: int, last_error: Exception):
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            f"Failed after {attempts} attempts. Last error: {last_error}"
        )


def _is_retryable(exc: Exception) -> bool:
    """Only retry transient server errors and rate limits."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout)):
        return True
    return False


def _get_retry_delay(exc: Exception, attempt: int,
                     base: float = 0.5, cap: float = 30.0) -> float:
    """Compute delay: honor Retry-After for 429, else bounded exponential."""
    if isinstance(exc, httpx.HTTPStatusError):
        retry_after = exc.response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), cap)
            except ValueError:
                pass
    delay = min(base * (2 ** attempt), cap)
    jitter = random.uniform(0, delay * 0.5)
    return delay + jitter


def with_retry(fn: Callable[..., T], *args,
               max_attempts: int = 4, **kwargs) -> T:
    """Call fn with retry on transient failures.

    - Only retries errors classified as transient
    - Honors Retry-After header on 429 responses
    - Exponential backoff with jitter, capped at 30s
    - Raises RetriesExhausted with attempt count + last error
    """
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if not _is_retryable(exc) or attempt == max_attempts - 1:
                break
            delay = _get_retry_delay(exc, attempt)
            logger.warning(
                "Attempt %d/%d failed (%s), retrying in %.1fs",
                attempt + 1, max_attempts, exc, delay,
            )
            time.sleep(delay)
    raise RetriesExhausted(attempts=max_attempts, last_error=last_exc)


def get_forecast(city: str) -> dict:
    def _call():
        resp = httpx.get(f"{BASE_URL}/forecast", params={"city": city})
        resp.raise_for_status()
        return resp.json()
    return with_retry(_call)


def get_alerts(region: str) -> list[dict]:
    def _call():
        resp = httpx.get(f"{BASE_URL}/alerts", params={"region": region})
        resp.raise_for_status()
        return resp.json()["alerts"]
    return with_retry(_call)
```

---

## Side-by-Side: What the KB Added

| Aspect | A (Base) | B (KB-Equipped) | Which pattern taught this |
|--------|----------|-----------------|--------------------------|
| **Retryable classification** | Retries everything | Only 429, 5xx, connection errors | Pattern 4 (meta-harness) |
| **429 Retry-After** | Ignored | Reads header, honors server timing | Pattern 2 (agents) |
| **Delay cap** | None (grows to 17+ min) | 30s maximum | Pattern 3 (claw-code) |
| **Jitter** | None (thundering herd) | Random 0–50% of delay | Pattern 3 (claw-code) |
| **Code reuse** | Copy-pasted per function | Shared `with_retry()` helper | Pattern 1 (MiroFish) |
| **Error context** | Loses retry count | `RetriesExhausted` with count + cause | Pattern 3 (claw-code) |
| **Logging** | None | Warning per retry with timing | Pattern 1 (MiroFish) |
| **Non-retryable errors** | Wasted retries on 400/404 | Fails fast, no wasted time | Pattern 4 (meta-harness) |

---

## Measured Results

These numbers are from the actual A/B script (`scripts/showcase_ab_retry.py`),
not estimates:

```
Run A:  0 patterns retrieved, 0.00 confidence, 0ms retrieval
Run B:  5 patterns retrieved, 0.56 confidence, 1,429ms retrieval

KB size: 2,895 methodologies from 250+ repos
Search:  Hybrid (vector similarity + BM25 text), top-5
```

The JSON output is saved to `data/showcase_ab_retry_results.json` for
programmatic inspection.

---

## How to Run This Yourself

### Prerequisites

```bash
git clone https://github.com/deesatzed/CAM-Pulse.git
cd CAM-Pulse
pip install -e ".[dev]"
```

### Run the A/B comparison script

```bash
PYTHONPATH=src python scripts/showcase_ab_retry.py
```

This queries the knowledge base with the retry task, displays the retrieval
results in Rich tables, and saves machine-readable JSON to
`data/showcase_ab_retry_results.json`.

### Run with execution (requires OpenRouter API key)

```bash
# Run A — empty KB baseline
cam create /tmp/cam-showcase \
    --request "Add retry logic with exponential backoff to weather_client.py" \
    --no-preflight --execute

# Run B — after mining repos to populate KB
cam mine /path/to/your/repos
cam create /tmp/cam-showcase \
    --request "Add retry logic with exponential backoff to weather_client.py" \
    --no-preflight --execute
```

---

## How It Works Under the Hood

```
                    ┌─────────────┐
                    │  New Task   │
                    │ "Add retry  │
                    │  logic..."  │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │   Hybrid    │
                    │   Search    │ ◄── 2,895 methodologies
                    │ (vector +   │     mined from 250+ repos
                    │   BM25)     │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
        ┌─────▼─────┐ ┌───▼───┐ ┌─────▼─────┐
        │ Pattern 1 │ │  ...  │ │ Pattern 5 │
        │ MiroFish  │ │       │ │ (prior    │
        │ retry +   │ │       │ │  task)    │
        │ backoff   │ │       │ │           │
        └─────┬─────┘ └───┬───┘ └─────┬─────┘
              │            │            │
              └────────────┼────────────┘
                           │
                    ┌──────▼──────┐
                    │  Assemble   │
                    │   Prompt    │
                    │             │
                    │ Task desc + │
                    │ Hints +     │
                    │ KB patterns │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  AI Agent   │
                    │  (Claude/   │
                    │   Codex/    │
                    │   etc.)     │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  Output:    │
                    │  Code with  │
                    │  retry,     │
                    │  jitter,    │
                    │  429-aware, │
                    │  bounded    │
                    └─────────────┘
```

1. **Task arrives** — plain-language description of what to build.
2. **Hybrid search** — finds the 5 most relevant mined patterns (1.4s).
3. **Prompt assembly** — injects hints and full pattern details into the
   agent's context window.
4. **Agent executes** — writes code informed by battle-tested patterns from
   real codebases, not just training data.
5. **Outcome feedback** — if the task succeeds, the patterns that helped
   get stronger (higher fitness score, lifecycle advances from
   embryonic → viable → thriving). If it fails, they weaken.

---

## Why This Matters

Without the knowledge base, the AI agent relies entirely on its training
data. The result is *functional but naive* — it works for the happy path but
breaks under real-world conditions (rate limits, thundering herds, permanent
errors wasting retry budget).

With the knowledge base, CAM surfaces **battle-tested patterns from real
codebases** — implementations that already handle the edge cases. The agent
doesn't have to rediscover these lessons; they're injected directly into its
context before it writes a single line.

**For novice users:** Think of it like giving a junior developer access to a
senior engineer's private notes before they start coding. The senior has
already solved this problem in 4 different projects and knows the pitfalls.

**For expert users:** CAM implements a lifecycle-managed RAG system where
mined methodologies are retrieved via hybrid search (384-dim BAAI/bge-small
vectors + BM25 FTS5), injected into the agent prompt as structured hints,
and refined through outcome-driven fitness feedback. The knowledge compounds:
each successful task strengthens the patterns that contributed.
