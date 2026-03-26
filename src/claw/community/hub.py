"""HuggingFace dataset hub for community knowledge sharing."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("claw.community.hub")

# Default community hub repo
DEFAULT_HF_REPO = "cam-community/knowledge-hub"


def _get_hf_token() -> Optional[str]:
    """Get HF token from environment."""
    return os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")


async def push_pack(
    records: list[dict[str, Any]],
    manifest: dict[str, Any],
    hf_repo: str = DEFAULT_HF_REPO,
    instance_id: str = "",
) -> str:
    """Push a community pack to HuggingFace dataset repo.

    Returns the URL of the published pack.
    """
    try:
        from huggingface_hub import HfApi
    except ImportError:
        raise RuntimeError("huggingface_hub not installed. Run: pip install huggingface_hub")

    token = _get_hf_token()
    if not token:
        raise ValueError("HF_TOKEN environment variable required for publishing")

    api = HfApi(token=token)

    # Write JSONL to temp file
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        for record in records:
            f.write(json.dumps(record) + "\n")
        jsonl_path = f.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(manifest, f, indent=2)
        manifest_path = f.name

    try:
        api.upload_file(
            path_or_fileobj=jsonl_path,
            path_in_repo=f"data/{instance_id}.jsonl",
            repo_id=hf_repo,
            repo_type="dataset",
        )
        api.upload_file(
            path_or_fileobj=manifest_path,
            path_in_repo=f"data/{instance_id}.manifest.json",
            repo_id=hf_repo,
            repo_type="dataset",
        )
        logger.info("Published %d records to %s", len(records), hf_repo)
        return f"https://huggingface.co/datasets/{hf_repo}"
    finally:
        Path(jsonl_path).unlink(missing_ok=True)
        Path(manifest_path).unlink(missing_ok=True)


async def list_contributors(hf_repo: str = DEFAULT_HF_REPO) -> list[dict[str, Any]]:
    """List all contributors in the community hub."""
    try:
        from huggingface_hub import HfApi
    except ImportError:
        raise RuntimeError("huggingface_hub not installed")

    token = _get_hf_token()
    api = HfApi(token=token)

    try:
        files = api.list_repo_files(repo_id=hf_repo, repo_type="dataset")
    except Exception as e:
        logger.warning("Could not list hub files: %s", e)
        return []

    contributors = []
    manifest_files = [f for f in files if f.endswith(".manifest.json") and f.startswith("data/")]

    for mf in manifest_files:
        try:
            import tempfile
            local = api.hf_hub_download(repo_id=hf_repo, filename=mf, repo_type="dataset", token=token)
            data = json.loads(Path(local).read_text())
            contributors.append(data)
        except Exception as e:
            logger.warning("Could not read manifest %s: %s", mf, e)

    return contributors


async def pull_contributor_pack(
    instance_id: str,
    hf_repo: str = DEFAULT_HF_REPO,
) -> list[dict[str, Any]]:
    """Pull a specific contributor's JSONL records from the hub."""
    try:
        from huggingface_hub import HfApi
    except ImportError:
        raise RuntimeError("huggingface_hub not installed")

    token = _get_hf_token()
    api = HfApi(token=token)

    try:
        local_path = api.hf_hub_download(
            repo_id=hf_repo,
            filename=f"data/{instance_id}.jsonl",
            repo_type="dataset",
            token=token,
        )
    except Exception as e:
        raise FileNotFoundError(f"Pack not found for {instance_id}: {e}")

    records = []
    for line in Path(local_path).read_text().strip().splitlines():
        if line.strip():
            records.append(json.loads(line))

    return records
