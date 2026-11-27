"""Single home for batch/sample selector normalization and name sanitizing.

Reads the active workspace's ``batch_prefix`` via ``te_analysis.paths.get_workspace()``
so configured batch prefixes (e.g. ``TE``, ``SNSE``) expand numeric shorthand while
prefix-free user workspaces preserve raw batch and sample names unchanged.
"""

from __future__ import annotations

import hashlib
import re

from te_analysis.paths import get_workspace


def _active_batch_prefix() -> str:
    return get_workspace().batch_prefix


def normalize_batch_id(selector: str, *, batch_prefix: str | None = None) -> str:
    """Normalize a batch selector using the workspace's configured batch_prefix."""
    selector = str(selector).strip()
    prefix = _active_batch_prefix() if batch_prefix is None else str(batch_prefix).strip().rstrip("-")
    if not prefix:
        return selector
    if selector.startswith("Batch-"):
        selector = selector.replace("Batch-", f"{prefix}-", 1)
    if selector.isdigit() or (selector and selector[0].isdigit()):
        selector = f"{prefix}-{selector}"
    return selector


def normalize_sample_selector(selector: str, *, batch_prefix: str | None = None) -> str:
    """Normalize like ``normalize_batch_id`` plus short-sample suffix expansion."""
    selector = str(selector).strip()
    prefix = _active_batch_prefix() if batch_prefix is None else str(batch_prefix).strip().rstrip("-")
    if not prefix:
        return selector
    if selector.startswith("Batch-"):
        selector = selector.replace("Batch-", f"{prefix}-", 1)
    if selector.isdigit():
        selector = f"{prefix}-{selector}"
    elif selector and selector[0].isdigit():
        selector = f"{prefix}-{selector}"
    short_sample_match = re.fullmatch(rf"({re.escape(prefix)}-\d+)([A-Za-z](?:-.+)?)", selector)
    if short_sample_match:
        batch_id, sample_suffix = short_sample_match.groups()
        selector = f"{batch_id}-{sample_suffix[:1].upper()}{sample_suffix[1:]}"
    return selector


def parse_batch_sample_selector(selector, *, batch_prefix: str | None = None):
    """
    Split selectors like TE-1054-B, 1054-B, TE-1054/B, or Batch01/SampleA.

    Returns (batch_id, sample_selector). sample_selector is None for a whole
    batch selector such as TE-1054.
    """
    raw = str(selector or "").strip()
    if not raw:
        return "", None

    prefix = _active_batch_prefix() if batch_prefix is None else str(batch_prefix).strip().rstrip("-")
    if not prefix:
        for sep in ("/", ":"):
            if sep in raw:
                batch_part, sample_part = raw.split(sep, 1)
                if sample_part:
                    return batch_part, f"{batch_part}{sep}{sample_part}"
        return raw, None

    normalized = raw.replace("Batch-", f"{prefix}-", 1)
    match = re.match(rf"^(?:{re.escape(prefix)}-)?(\d+)(?:([-/:])(.+))?$", normalized)
    if not match:
        for sep in ("/", ":"):
            if sep in normalized:
                batch_part, sample_part = normalized.split(sep, 1)
                norm_b = normalize_batch_id(batch_part, batch_prefix=prefix)
                return norm_b, (f"{norm_b}{sep}{sample_part}" if sample_part else None)
        return normalize_batch_id(normalized, batch_prefix=prefix), None

    batch_id = f"{prefix}-{match.group(1)}"
    separator = match.group(2) or "-"
    sample_part = match.group(3)
    if not sample_part:
        return batch_id, None

    return batch_id, f"{batch_id}{separator}{sample_part}"


def parse_qualified_sample_selector(selector, *, batch_prefix: str | None = None):
    """Return a scoped sample selector when the selector includes a batch id."""
    batch_id, sample_selector = parse_batch_sample_selector(selector, batch_prefix=batch_prefix)
    if sample_selector:
        return batch_id, sample_selector
    return "", str(selector or "").strip()


def truncate_with_digest(value: str, max_length: int = 96) -> str:
    """Cap a sanitized name at max_length, keeping uniqueness via a hash tail."""
    if len(value) <= max_length:
        return value
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    prefix_length = max(1, max_length - len(digest) - 1)
    return f"{value[:prefix_length].rstrip('_.-')}_{digest}"
