# payload.py - API Payload Construction

## Purpose
Transforms Open WebUI's internal request parameters into the correct format for downstream LLM APIs (OpenAI-compatible and Ollama).

## Key Functions

### apply_system_prompt_to_body()
Injects or replaces the system prompt in the messages array, with variable substitution support.

### apply_model_params_to_body_openai()
Applies model parameters to an OpenAI-compatible API payload:
- Removes Open WebUI-internal params (stream_response, function_calling, reasoning_tags, system)
- Merges `custom_params` (arbitrary user-defined key-value pairs) into params
- Defaults `use_tools` to `False` if not explicitly set (prevents server-side tool use unless opted in)
- Casts known parameters to correct types via mappings (temperature->float, max_tokens->int, etc.)
- Unknown parameters pass through as-is

### apply_model_params_to_body_ollama()
Same as OpenAI variant but wraps params in Ollama's `options` field and remaps parameter names (e.g., max_tokens -> num_predict).

### convert_payload_openai_to_ollama()
Full payload conversion from OpenAI format to Ollama format, including message format conversion and parameter remapping.

## Custom Parameters
The `custom_params` dict allows arbitrary key-value pairs to be injected into the payload. Values that are JSON strings are auto-parsed. These are merged into params before type-casting, so they can override any default.

## Change History
- 2026-03-31: Added default `use_tools: false` injection into OpenAI payloads to disable server-side tool use by default
