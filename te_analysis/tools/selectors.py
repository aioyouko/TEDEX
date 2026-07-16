"""Single home for batch/sample selector normalization and name sanitizing.

These functions were previously duplicated across run_analysis.py,
plot_te.py, and plot_xrd_data.py. Behavior is preserved verbatim; note the
two normalizers intentionally differ:

- ``normalize_batch_id``: prefix handling only ("1054" -> "CHY-1054").
- ``normalize_sample_selector``: also expands short sample suffixes
  ("CHY-1054B" -> "CHY-1054-B").
"""

from __future__ import annotations

import hashlib
import re


def normalize_batch_id(selector: str) -> str:
    """Normalize a batch selector: Batch- prefix and bare/leading digits."""
    selector = str(selector).strip()
    if selector.startswith("Batch-"):
        selector = selector.replace("Batch-", "CHY-", 1)
    if selector.isdigit() or (selector and selector[0].isdigit()):
        selector = f"CHY-{selector}"
    return selector


def normalize_sample_selector(selector: str) -> str:
    """Normalize like ``normalize_batch_id`` plus short-sample expansion."""
    selector = selector.strip()
    if selector.startswith("Batch-"):
        selector = selector.replace("Batch-", "CHY-", 1)
    if selector.isdigit():
        selector = f"CHY-{selector}"
    elif selector and selector[0].isdigit():
        selector = f"CHY-{selector}"
    short_sample_match = re.fullmatch(r"(CHY-\d+)([A-Za-z](?:-.+)?)", selector)
    if short_sample_match:
        batch_id, sample_suffix = short_sample_match.groups()
        selector = f"{batch_id}-{sample_suffix[:1].upper()}{sample_suffix[1:]}"
    return selector


def parse_batch_sample_selector(selector):
    """
    Split selectors like CHY-1054-B, 1054-B, CHY-1054/B, or CHY-1054:B.

    Returns (batch_id, sample_selector). sample_selector is None for a whole
    batch selector such as CHY-1054.
    """
    raw = str(selector or "").strip()
    if not raw:
        return "", None

    normalized = raw.replace("Batch-", "CHY-", 1)
    match = re.match(r"^(?:CHY-)?(\d+)(?:[-/:](.+))?$", normalized)
    if not match:
        return normalize_batch_id(normalized), None

    batch_id = f"CHY-{match.group(1)}"
    sample_part = match.group(2)
    if not sample_part:
        return batch_id, None

    separator = "/" if "/" in normalized else ":" if ":" in normalized else "-"
    return batch_id, f"{batch_id}{separator}{sample_part}"


def parse_qualified_sample_selector(selector):
    """Return a scoped sample selector when the selector includes a batch id."""
    batch_id, sample_selector = parse_batch_sample_selector(selector)
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
