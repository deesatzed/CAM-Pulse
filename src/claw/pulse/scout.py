"""X-Scout: Searches X via Grok API's native x_search tool for GitHub repos.

Uses the xAI Responses API (/v1/responses) with the built-in x_search tool
to discover novel GitHub repositories mentioned on X (Twitter).
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from claw.core.config import PulseConfig
from claw.pulse.models import PulseDiscovery

logger = logging.getLogger("claw.pulse.scout")

# xAI Responses API endpoint
XAI_RESPONSES_URL = "https://api.x.ai/v1/responses"

# Pattern to match GitHub repo URLs: github.com/{owner}/{repo}
_GITHUB_REPO_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)

# URLs to skip (not actual repos)
_GITHUB_SKIP_PATHS = {
    "topics", "explore", "trending", "collections", "sponsors",
    "marketplace", "settings", "notifications", "login", "signup",
    "orgs", "features", "security", "customer-stories", "about",
    "pricing", "enterprise", "team", "join",
}


class XScout:
    """Searches X via Grok API's native x_search tool for GitHub repos."""

    def __init__(self, config: PulseConfig):
        self.config = config
        self.xai_api_key = os.getenv(config.xai_api_key_env, "")
        self.model = config.xai_model
        self._timeout = httpx.Timeout(120.0, connect=15.0)

    async def scan(
        self,
        keywords: Optional[list[str]] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> list[PulseDiscovery]:
        """Execute x_search for each keyword, extract GitHub URLs.

        Args:
            keywords: Search queries. Defaults to config.keywords.
            from_date: ISO8601 date (YYYY-MM-DD). Defaults to today.
            to_date: ISO8601 date (YYYY-MM-DD). Defaults to today.

        Returns:
            List of PulseDiscovery objects (deduplicated by canonical URL).
        """
        if not self.xai_api_key:
            logger.error("XAI_API_KEY not set — cannot scan X")
            return []

        if not self.model:
            logger.error("pulse.xai_model not configured in claw.toml")
            return []

        keywords = keywords or self.config.keywords
        if not from_date:
            from_date = datetime.now(UTC).strftime("%Y-%m-%d")
        if not to_date:
            to_date = from_date

        # Profile-aware keyword enrichment: append domain terms to each keyword
        keywords = self._enrich_keywords(keywords)

        scan_id = str(uuid.uuid4())[:8]
        all_discoveries: dict[str, PulseDiscovery] = {}

        for kw in keywords:
            try:
                result = await self._x_search(kw, from_date, to_date)
                urls = self._extract_discoveries_from_response(result, kw, scan_id)
                for disc in urls:
                    if disc.canonical_url not in all_discoveries:
                        all_discoveries[disc.canonical_url] = disc
                    else:
                        # Merge keywords
                        existing = all_discoveries[disc.canonical_url]
                        for k in disc.keywords_matched:
                            if k not in existing.keywords_matched:
                                existing.keywords_matched.append(k)
            except httpx.ConnectError:
                logger.error("Cannot reach xAI API at %s", XAI_RESPONSES_URL)
            except httpx.HTTPStatusError as e:
                logger.error("xAI API error %d: %s", e.response.status_code, e.response.text[:200])
            except Exception as e:
                logger.error("X-Scout scan error for keyword %r: %s", kw, e)

        discoveries = list(all_discoveries.values())
        logger.info(
            "X-Scout scan complete: %d keywords → %d unique repos",
            len(keywords), len(discoveries),
        )
        return discoveries

    async def _x_search(self, query: str, from_date: str, to_date: str) -> dict:
        """Single x_search API call via httpx.

        Returns the raw JSON response from xAI Responses API.
        """
        tool_spec: dict[str, Any] = {"type": "x_search"}
        if from_date:
            tool_spec["from_date"] = from_date
        if to_date:
            tool_spec["to_date"] = to_date

        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "user",
                    "content": (
                        f"Search X for posts containing GitHub repository links "
                        f"matching: {query}. "
                        f"List every distinct github.com URL you find with a brief "
                        f"description of what the repo does. "
                        f"Include the X post author handle and post URL if available."
                    ),
                }
            ],
            "tools": [tool_spec],
            "inline_citations": True,
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                XAI_RESPONSES_URL,
                headers={
                    "Authorization": f"Bearer {self.xai_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    def _extract_discoveries_from_response(
        self,
        response: dict,
        keyword: str,
        scan_id: str,
    ) -> list[PulseDiscovery]:
        """Parse xAI response to extract GitHub URLs and metadata."""
        discoveries = []

        # Extract text content from response output
        text_parts = []
        output = response.get("output", [])
        if isinstance(output, list):
            for item in output:
                if isinstance(item, dict):
                    content = item.get("content", "")
                    if isinstance(content, str):
                        text_parts.append(content)
                    elif isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict):
                                text_parts.append(block.get("text", "") or "")
        elif isinstance(output, str):
            text_parts.append(output)

        full_text = "\n".join(text_parts)

        # Also check top-level text field
        if "text" in response and isinstance(response["text"], str):
            full_text += "\n" + response["text"]

        # Extract GitHub URLs
        urls = self.extract_github_urls(full_text)

        for url in urls:
            canonical = self.canonical_github_url(url)
            disc = PulseDiscovery(
                github_url=url,
                canonical_url=canonical,
                x_post_text=full_text[:500],
                keywords_matched=[keyword],
                scan_id=scan_id,
            )
            # Try to extract X handle from text context around the URL
            handle = self._extract_handle_near_url(full_text, url)
            if handle:
                disc.x_author_handle = handle
            discoveries.append(disc)

        return discoveries

    @staticmethod
    def extract_github_urls(text: str) -> list[str]:
        """Extract and deduplicate GitHub repo URLs from text."""
        matches = _GITHUB_REPO_PATTERN.findall(text)
        seen = set()
        urls = []
        for owner, repo in matches:
            # Skip non-repo paths
            if owner.lower() in _GITHUB_SKIP_PATHS:
                continue
            # Clean up repo name (strip .git, trailing punctuation)
            repo = repo.rstrip(".,;:!?)\"'")
            if repo.endswith(".git"):
                repo = repo[:-4]
            if not repo or repo.startswith("."):
                continue
            canonical = f"https://github.com/{owner}/{repo}"
            if canonical.lower() not in seen:
                seen.add(canonical.lower())
                urls.append(canonical)
        return urls

    @staticmethod
    def canonical_github_url(url: str) -> str:
        """Normalize GitHub URL to canonical form.

        Strips .git suffix, trailing slashes, query params, fragments.
        Returns https://github.com/{owner}/{repo} in lowercase.
        """
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        # Remove .git suffix
        if path.endswith(".git"):
            path = path[:-4]
        # Take only owner/repo (ignore deeper paths like /tree/main)
        parts = path.split("/")
        if len(parts) >= 2:
            path = f"{parts[0]}/{parts[1]}"
        return f"https://github.com/{path}".lower()

    @staticmethod
    def _extract_handle_near_url(text: str, url: str) -> str:
        """Try to find an @handle near a URL mention in the text."""
        idx = text.find(url)
        if idx < 0:
            # Try just the repo path
            parsed = urlparse(url)
            idx = text.find(parsed.path.strip("/"))
        if idx < 0:
            return ""
        # Look in the 200 chars before the URL
        window = text[max(0, idx - 200):idx]
        handle_match = re.findall(r"@([A-Za-z0-9_]+)", window)
        if handle_match:
            return handle_match[-1]  # Closest handle before the URL
        return ""

    def _enrich_keywords(self, keywords: list[str]) -> list[str]:
        """Enrich keywords with profile domains if configured.

        If profile.domains is set, appends domain terms to each keyword
        to focus the search. E.g., keyword "github.com new repo" with
        domains ["memory", "RAG"] becomes "github.com new repo memory RAG".
        """
        domains = getattr(self.config, "profile", None)
        if domains is None:
            return keywords
        domain_list = getattr(domains, "domains", [])
        if not domain_list:
            return keywords

        # Append up to 3 domain terms per keyword to keep queries focused
        domain_suffix = " ".join(domain_list[:3])
        enriched = [f"{kw} {domain_suffix}" for kw in keywords]
        logger.info("Profile-enriched keywords: %s", enriched)
        return enriched

    def check_api_key(self) -> tuple[bool, str]:
        """Validate that XAI_API_KEY is set and non-empty.

        Returns (ok, message) tuple.
        """
        if not self.xai_api_key:
            return False, f"Environment variable {self.config.xai_api_key_env} is not set"
        if not self.model:
            return False, "pulse.xai_model is not configured in claw.toml"
        return True, f"XAI key set (prefix: {self.xai_api_key[:8]}...), model: {self.model}"
