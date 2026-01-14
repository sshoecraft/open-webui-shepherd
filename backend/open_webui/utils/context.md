# Context Overflow Handling

This module implements reactive context overflow handling for Open WebUI. When a backend returns a "context length exceeded" error, the system automatically evicts older messages and retries.

## How It Works

1. **Error Detection**: When the backend returns HTTP 400 with a context overflow error message, Open WebUI detects it
2. **Token Parsing**: Parses the error message to determine how many tokens need to be freed
3. **Message Eviction**: Uses a two-pass strategy to intelligently remove older messages
4. **Retry**: Resends the request with the reduced message list

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

## Files

- `backend/open_webui/utils/context.py` - Eviction logic
- `backend/open_webui/routers/openai.py` - Retry integration

## Limitations

1. **Streaming Responses**: Retry only works for non-streaming requests. For streaming, context errors appear in the stream.

2. **Token Estimation**: When error parsing fails, falls back to character-based estimation (~4 chars/token).

3. **RAG Context**: Evicted messages may include RAG-augmented content. The system doesn't distinguish between original and augmented messages.

## Testing

1. Use a model with small context (e.g., 4K tokens)
2. Have a long conversation that fills context
3. Send another message
4. Check logs for: `"Context overflow detected: need to free X tokens"`
5. Verify response succeeds after eviction

## History

- v0.1.0: Initial implementation based on Shepherd's eviction strategy
