"""
Context overflow handling utilities.

Implements reactive eviction when backends return "context length exceeded" errors.
Based on Shepherd's two-pass eviction strategy (session.cpp).
"""

import re
import json
import logging
from typing import Optional

log = logging.getLogger(__name__)

# Maximum retry attempts for context overflow
MAX_CONTEXT_RETRIES = 3


def is_context_overflow_error(error_response: dict | str) -> bool:
    """
    Check if an error response indicates context length exceeded.

    Args:
        error_response: Error response from backend (dict or string)

    Returns:
        True if this is a context overflow error
    """
    if isinstance(error_response, dict):
        error_msg = error_response.get("error", {})
        if isinstance(error_msg, dict):
            error_msg = error_msg.get("message", "")
        elif isinstance(error_msg, str):
            pass
        else:
            error_msg = str(error_msg)
    else:
        error_msg = str(error_response)

    error_msg = error_msg.lower()

    keywords = [
        "context length",
        "maximum context",
        "token limit",
        "too many tokens",
        "context size",
        "n_ctx",
        "exceed",
        "tokens but limit",
    ]

    return any(kw in error_msg for kw in keywords)


def parse_overflow_error(error_message: str) -> int:
    """
    Parse context overflow error message to extract tokens_to_evict.

    Handles multiple error formats:
    - Shepherd: "would need X tokens but limit is Y tokens"
    - OpenAI classic: "maximum context length is X tokens. However, your messages resulted in Y tokens"
    - vLLM detailed: "is too large: X. ... maximum context length is Y ... your request has Z input tokens"
    - vLLM simple: "maximum context length is X ... your request has Y input tokens"
    - OpenAI detailed: "you requested X tokens (Y in the messages, Z in the completion)"
    - llama.cpp JSON: {"error":{"n_prompt_tokens":X,"n_ctx":Y}}

    Args:
        error_message: Error message from backend

    Returns:
        Number of tokens to evict (actual - max), or -1 if can't parse
    """
    actual_tokens = -1
    max_tokens = -1

    # Try to parse as JSON first (llama.cpp format)
    try:
        parsed = json.loads(error_message)
        if isinstance(parsed, dict):
            error_obj = parsed.get("error", parsed)
            if isinstance(error_obj, dict):
                n_prompt = error_obj.get("n_prompt_tokens", -1)
                n_ctx = error_obj.get("n_ctx", -1)
                if n_prompt > 0 and n_ctx > 0:
                    log.debug(f"Parsed llama.cpp JSON: n_prompt={n_prompt}, n_ctx={n_ctx}")
                    return n_prompt - n_ctx
    except (json.JSONDecodeError, TypeError):
        pass

    # Shepherd format: "would need X tokens but limit is Y tokens"
    match = re.search(r"would need (\d+) tokens but limit is (\d+)", error_message)
    if match:
        actual_tokens = int(match.group(1))
        max_tokens = int(match.group(2))
        log.debug(f"Parsed Shepherd format: actual={actual_tokens}, max={max_tokens}")
        return actual_tokens - max_tokens

    # OpenAI classic: "maximum context length is X tokens. However, your messages resulted in Y tokens"
    match = re.search(
        r"maximum context length is (\d+) tokens.*?resulted in (\d+) tokens",
        error_message,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        max_tokens = int(match.group(1))
        actual_tokens = int(match.group(2))
        log.debug(f"Parsed OpenAI classic format: actual={actual_tokens}, max={max_tokens}")
        return actual_tokens - max_tokens

    # vLLM MAX_TOKENS_TOO_HIGH: "is too large: X. ... maximum context length is Y ... your request has Z input tokens"
    too_large_match = re.search(r"is too large: (\d+)", error_message)
    max_ctx_match = re.search(r"maximum context length is (\d+)", error_message, re.IGNORECASE)
    request_match = re.search(r"your request has (\d+)", error_message, re.IGNORECASE)

    if too_large_match and max_ctx_match and request_match:
        max_tokens_requested = int(too_large_match.group(1))
        max_context = int(max_ctx_match.group(1))
        actual_prompt = int(request_match.group(1))
        overflow = actual_prompt + max_tokens_requested - max_context
        log.debug(
            f"Parsed vLLM MAX_TOKENS_TOO_HIGH: prompt={actual_prompt}, "
            f"max_requested={max_tokens_requested}, max_ctx={max_context}, overflow={overflow}"
        )
        return overflow if overflow > 0 else -1

    # vLLM simple: "maximum context length is X ... your request has Y input tokens"
    if max_ctx_match and request_match:
        max_tokens = int(max_ctx_match.group(1))
        actual_tokens = int(request_match.group(1))
        log.debug(f"Parsed vLLM simple format: actual={actual_tokens}, max={max_tokens}")
        return actual_tokens - max_tokens

    # OpenAI detailed: "you requested X tokens (Y in the messages, Z in the completion)"
    match = re.search(
        r"maximum context length is (\d+).*?you requested (\d+) tokens",
        error_message,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        max_tokens = int(match.group(1))
        actual_tokens = int(match.group(2))
        log.debug(f"Parsed OpenAI detailed format: actual={actual_tokens}, max={max_tokens}")
        return actual_tokens - max_tokens

    log.debug(f"Could not parse token count from error: {error_message[:200]}")
    return -1


def compute_chars_per_token_ema(messages: list[dict]) -> float:
    """
    Compute chars_per_token ratio using EMA from message history.

    Replicates Shepherd's EMA approach (backends/openai.cpp lines 1148-1158):
    - actual_ratio = content.length() / tokens
    - Only update if deviation is within 0.5x-2x (outlier rejection)
    - EMA: chars_per_token = 0.8 * chars_per_token + 0.2 * actual_ratio
    - Clamp between 2.0 and 5.0

    Args:
        messages: List of message dicts with content and optionally usage

    Returns:
        Computed chars_per_token ratio (default 4.0 if no data)
    """
    chars_per_token = 4.0  # Starting estimate
    alpha = 0.2

    for msg in messages:
        if msg.get("role") != "assistant":
            continue

        usage = msg.get("usage", {})
        completion = usage.get("completion_tokens", 0) if usage else 0
        content = msg.get("content", "")

        if completion > 0 and len(content) > 0:
            actual_ratio = len(content) / completion
            deviation_ratio = actual_ratio / chars_per_token

            # Outlier rejection: only update if within 0.5x-2x
            if 0.5 <= deviation_ratio <= 2.0:
                chars_per_token = (1.0 - alpha) * chars_per_token + alpha * actual_ratio
                # Clamp between 2.0 and 5.0
                chars_per_token = max(2.0, min(5.0, chars_per_token))

    return chars_per_token


def estimate_tokens(content: str, chars_per_token: float = 4.0) -> int:
    """Estimate token count from content length using chars_per_token ratio."""
    if not content:
        return 0
    return int(len(content) / chars_per_token)


def compute_message_tokens(messages: list[dict]) -> list[int]:
    """
    Compute token counts for all messages using delta calculation.

    Replicates Shepherd's approach (backends/openai.cpp):
        user_tokens = prompt_tokens[current] - last_prompt_tokens
        last_prompt_tokens = prompt_tokens + completion_tokens (after assistant response)
        assistant_tokens = completion_tokens if > 0, else estimate from content

    Args:
        messages: List of message dicts with 'role', 'content', and optionally 'usage'

    Returns:
        List of token counts, one per message
    """
    n = len(messages)
    tokens = [0] * n

    # Compute EMA chars_per_token from message history for fallback estimates
    chars_per_token = compute_chars_per_token_ema(messages)

    # Build list of (index, prompt_tokens, completion_tokens) for assistant msgs with usage
    assistant_usages = []
    for i, msg in enumerate(messages):
        usage = msg.get("usage", {})
        if msg.get("role") == "assistant":
            prompt = usage.get("prompt_tokens", 0) if usage else 0
            completion = usage.get("completion_tokens", 0) if usage else 0
            assistant_usages.append((i, prompt, completion))

    # Set assistant token counts: completion_tokens if > 0, else estimate from content
    for idx, prompt, completion in assistant_usages:
        if completion > 0:
            tokens[idx] = completion
        else:
            content = messages[idx].get("content", "")
            tokens[idx] = estimate_tokens(content, chars_per_token)

    # Calculate user message tokens from deltas
    # last_prompt_tokens tracks: prompt_tokens + completion_tokens after each assistant turn
    last_prompt_tokens = 0
    asst_idx = 0

    for i, msg in enumerate(messages):
        role = msg.get("role")

        if role == "user":
            # Find next assistant after this user message
            while asst_idx < len(assistant_usages) and assistant_usages[asst_idx][0] < i:
                asst_idx += 1

            if asst_idx < len(assistant_usages):
                next_idx, next_prompt, next_completion = assistant_usages[asst_idx]
                if next_prompt > 0 and last_prompt_tokens > 0:
                    # Delta calculation: user_tokens = prompt_tokens - last_prompt_tokens
                    user_tokens = next_prompt - last_prompt_tokens
                    tokens[i] = max(0, user_tokens)
                elif next_prompt > 0:
                    # First user message: includes system prompt
                    tokens[i] = next_prompt
                else:
                    # No prompt_tokens available, estimate from content
                    content = msg.get("content", "")
                    tokens[i] = estimate_tokens(content, chars_per_token)
            else:
                # No following assistant, estimate from content
                content = msg.get("content", "")
                tokens[i] = estimate_tokens(content, chars_per_token)

        elif role == "assistant":
            usage = msg.get("usage", {})
            prompt = usage.get("prompt_tokens", 0) if usage else 0
            completion = usage.get("completion_tokens", 0) if usage else 0
            if prompt > 0:
                # Update baseline: last_prompt_tokens = prompt_tokens + completion_tokens
                last_prompt_tokens = prompt + completion

        elif role == "tool":
            # Tool messages: estimate from content
            content = msg.get("content", "")
            tokens[i] = estimate_tokens(content, chars_per_token)

    return tokens


def calculate_turns_to_evict(
    messages: list[dict], tokens_needed: int
) -> list[tuple[int, int]]:
    """
    Calculate message ranges to evict using two-pass strategy.

    Pass 1: Complete turns (USER -> final ASSISTANT)
    Pass 2: Mini-turns (tool call pairs) from current turn

    Based on Shepherd's session.cpp calculate_messages_to_evict().

    Args:
        messages: List of message dicts
        tokens_needed: Number of tokens to free

    Returns:
        List of (start_idx, end_idx) ranges to remove (inclusive)
    """
    ranges = []
    tokens_freed = 0

    # Precompute token counts using delta calculation
    token_counts = compute_message_tokens(messages)

    # Find last user message (current turn - protected)
    last_user_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            last_user_idx = i
            break

    if last_user_idx < 0:
        log.debug("No user messages found, cannot evict")
        return []

    # PASS 1: Evict complete turns (USER -> final ASSISTANT)
    log.debug("Pass 1: Looking for complete turns to evict")
    i = 0
    while i < len(messages) and tokens_freed < tokens_needed:
        # Stop before current user message
        if i >= last_user_idx:
            break

        # Skip system messages
        if messages[i].get("role") == "system":
            i += 1
            continue

        # Skip non-user messages at start
        if messages[i].get("role") != "user":
            i += 1
            continue

        # Found USER - scan forward for final ASSISTANT
        turn_start = i
        turn_tokens = token_counts[i]
        i += 1

        final_assistant_idx = -1
        while i < last_user_idx:
            turn_tokens += token_counts[i]
            role = messages[i].get("role")

            if role == "assistant":
                # Check if this is final assistant (next is user or end)
                if i + 1 >= len(messages) or i + 1 >= last_user_idx or messages[i + 1].get("role") == "user":
                    final_assistant_idx = i
                    i += 1
                    break
            i += 1

        if final_assistant_idx >= 0:
            ranges.append((turn_start, final_assistant_idx))
            tokens_freed += turn_tokens
            log.debug(
                f"Pass 1: Evicting turn [{turn_start}, {final_assistant_idx}] "
                f"freeing ~{turn_tokens} tokens"
            )

    if tokens_freed >= tokens_needed:
        log.debug(f"Pass 1 freed ~{tokens_freed} tokens (needed {tokens_needed})")
        return ranges

    # PASS 2: Evict mini-turns (ASSISTANT + tool pairs) from current turn
    log.debug(f"Pass 2: Need ~{tokens_needed - tokens_freed} more tokens")

    if last_user_idx >= 0 and last_user_idx + 1 < len(messages):
        i = last_user_idx + 1
        while i < len(messages) - 1 and tokens_freed < tokens_needed:
            # Look for ASSISTANT + tool pairs
            if (
                messages[i].get("role") == "assistant"
                and i + 1 < len(messages)
                and messages[i + 1].get("role") == "tool"
            ):
                # Skip if this is the last assistant (protect context)
                # Find last assistant index
                last_assistant_idx = -1
                for j in range(len(messages) - 1, last_user_idx, -1):
                    if messages[j].get("role") == "assistant":
                        last_assistant_idx = j
                        break

                if i == last_assistant_idx:
                    log.debug(f"Pass 2: Skipping protected last assistant at {i}")
                    i += 2
                    continue

                pair_tokens = token_counts[i] + token_counts[i + 1]
                ranges.append((i, i + 1))
                tokens_freed += pair_tokens
                log.debug(
                    f"Pass 2: Evicting mini-turn [{i}, {i + 1}] "
                    f"freeing ~{pair_tokens} tokens"
                )
                i += 2
                continue

            i += 1

    log.debug(f"Total freed: ~{tokens_freed} tokens (needed {tokens_needed})")
    return ranges


def evict_messages(messages: list[dict], tokens_needed: int) -> tuple[list[dict], list[str]]:
    """
    Remove messages from list to free context space.

    Args:
        messages: Original message list
        tokens_needed: Tokens to free

    Returns:
        Tuple of (new message list with evicted messages removed, list of evicted message IDs)
    """
    if tokens_needed <= 0:
        return messages, []

    ranges = calculate_turns_to_evict(messages, tokens_needed)
    if not ranges:
        log.warning("No messages available for eviction")
        return messages, []

    # Collect evicted message IDs before removing
    evicted_ids = []
    for start, end in ranges:
        for i in range(start, end + 1):
            msg_id = messages[i].get("id")
            if msg_id:
                evicted_ids.append(msg_id)

    # Remove ranges in reverse order to preserve indices
    result = messages.copy()
    for start, end in reversed(ranges):
        result = result[:start] + result[end + 1 :]

    evicted_count = len(messages) - len(result)
    log.info(f"Evicted {evicted_count} messages to free context space")
    return result, evicted_ids


def evict_messages_fallback(messages: list[dict], percentage: float = 0.25) -> tuple[list[dict], list[str]]:
    """
    Fallback eviction: remove percentage of oldest non-system messages.

    Used when error message parsing fails.

    Args:
        messages: Original message list
        percentage: Fraction of messages to remove (default 25%)

    Returns:
        Tuple of (new message list with evicted messages removed, list of evicted message IDs)
    """
    # Find first non-system message
    start_idx = 0
    for i, msg in enumerate(messages):
        if msg.get("role") != "system":
            start_idx = i
            break

    # Protect last user message and beyond
    last_user_idx = len(messages) - 1
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            last_user_idx = i
            break

    evictable_count = last_user_idx - start_idx
    if evictable_count <= 0:
        return messages, []

    to_remove = max(1, int(evictable_count * percentage))
    end_idx = start_idx + to_remove

    # Collect evicted message IDs
    evicted_ids = []
    for i in range(start_idx, end_idx):
        msg_id = messages[i].get("id")
        if msg_id:
            evicted_ids.append(msg_id)

    log.info(f"Fallback eviction: removing {to_remove} messages ({percentage*100:.0f}%)")
    return messages[:start_idx] + messages[end_idx:], evicted_ids
