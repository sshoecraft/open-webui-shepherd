# Context Overflow Handling

This module implements reactive context overflow handling for Open WebUI. When a backend returns a "context length exceeded" error, the system automatically evicts older messages and retries.

## How It Works

1. **Error Detection**: When the backend returns HTTP 400 with a context overflow error message, Open WebUI detects it
2. **Token Parsing**: Parses the error message to determine how many tokens need to be freed
3. **Message Eviction**: Uses a two-pass strategy to intelligently remove older messages
4. **Persistence**: Evicted message IDs are marked with `evicted: true` in the database
5. **Frontend Filtering**: Subsequent requests filter out evicted messages before building the API payload
6. **Retry**: Resends the request with the reduced message list

## Two-Pass Eviction Strategy

Based on Shepherd's eviction algorithm (session.cpp):

### Pass 1: Big-Turns
Complete conversation exchanges (USER → final ASSISTANT) are evicted first:
```
USER: "What is Python?"
ASSISTANT (tool_call): search_web(...)
TOOL: {...results...}
ASSISTANT: "Python is a programming language..."
```

All messages in a complete turn are evicted together. This preserves conversation coherence.

### Pass 2: Mini-Turns
If Pass 1 doesn't free enough space, intermediate tool exchanges within the current turn are evicted:
```
ASSISTANT (tool_call): function_a()  ← evicted
TOOL: result_a                        ← evicted
ASSISTANT (tool_call): function_b()  ← kept (last assistant provides context)
TOOL: result_b
```

### Protected Messages
- System message (index 0)
- Current user message (the one being responded to)
- Last assistant message (provides context for tool results)

## Supported Error Formats

The error parser handles multiple backend formats:

| Backend | Error Format |
|---------|--------------|
| Shepherd | `"would need X tokens but limit is Y tokens"` |
| OpenAI | `"maximum context length is X tokens. However, your messages resulted in Y tokens"` |
| vLLM | `"maximum context length is X ... your request has Y input tokens"` |
| llama.cpp | `{"error": {"n_prompt_tokens": X, "n_ctx": Y}}` |

## Backend Compatibility

| Backend | Returns Error | Retry Works |
|---------|---------------|-------------|
| OpenAI API | Yes | Yes |
| vLLM | Yes | Yes |
| llama.cpp server | Yes | Yes |
| Shepherd | Yes | Yes |
| Ollama | No (silent truncation) | N/A |

**Note**: Ollama silently truncates context instead of returning errors. It drops oldest tokens automatically.

## Configuration

```python
MAX_CONTEXT_RETRIES = 3  # Maximum retry attempts
```

## Eviction Persistence

When messages are evicted:

1. **Backend marks messages**: `Chats.mark_messages_as_evicted(chat_id, evicted_ids)` sets `evicted: true` on each message in the database
2. **Frontend filters**: `Chat.svelte` filters out messages with `evicted: true` before building API payloads
3. **User visibility**: Evicted messages remain visible in the chat UI (history preserved) but are excluded from future API calls

### Database Schema

Messages are stored in `chat.chat.history.messages` as a dictionary keyed by message ID:
```json
{
  "msg-uuid-123": {
    "id": "msg-uuid-123",
    "role": "user",
    "content": "...",
    "evicted": true  // Added when evicted
  }
}
```

### Edge Cases

- **Temporary chats**: `local:*` chat IDs skip database updates
- **Missing IDs**: Messages without `id` field are evicted from the payload but not tracked
- **Branching**: Children of evicted messages remain accessible via parentId navigation

## Files

- `backend/open_webui/utils/context.py` - Eviction logic (returns evicted message IDs)
- `backend/open_webui/routers/openai.py` - Retry integration and DB persistence
- `backend/open_webui/models/chats.py` - `mark_messages_as_evicted()` method
- `src/lib/components/chat/Chat.svelte` - Frontend filtering of evicted messages

## Token Counting

Token counts are calculated using delta calculation based on Shepherd's approach:

### Algorithm

For assistant messages, token count comes directly from `usage.completion_tokens`.

For user messages, tokens are calculated from the delta between consecutive assistant responses:
```
user_tokens = next_assistant.prompt_tokens - prev_assistant.prompt_tokens - prev_assistant.completion_tokens
```

### Example

For a message sequence:
```
user1 -> assistant1(prompt=1000, completion=200) -> user2 -> assistant2(prompt=1400, completion=300)
```

- `user1_tokens = 1000` (first assistant's prompt_tokens includes system prompt)
- `user2_tokens = 1400 - 1000 - 200 = 200`
- `assistant1_tokens = 200` (completion_tokens)
- `assistant2_tokens = 300` (completion_tokens)

This approach provides accurate token counts by leveraging the usage data already returned by LLM backends.

## Limitations

1. **Streaming Responses**: Retry only works for non-streaming requests. For streaming, context errors appear in the stream.

2. **RAG Context**: Evicted messages may include RAG-augmented content. The system doesn't distinguish between original and augmented messages.

3. **Missing Usage Data**: If assistant messages lack usage data, their token counts and preceding user messages will be 0.

## Testing

1. Use a model with small context (e.g., 4K tokens)
2. Have a long conversation that fills context
3. Send another message
4. Check logs for: `"Context overflow detected: need to free X tokens"`
5. Verify response succeeds after eviction

## History

- v0.3.0: Replaced character-based token estimation with delta calculation using actual usage data from assistant responses
- v0.2.0: Added eviction persistence - evicted messages are marked in database and filtered from future requests
- v0.1.0: Initial implementation based on Shepherd's eviction strategy
