# Shepherd Tool Server Integration

This module provides direct integration with Shepherd's tool API, allowing Open WebUI to use Shepherd as a tool server without requiring an MCP proxy.

## Architecture

```
Open WebUI → HTTP → Shepherd API
                    /v1/tools (list tools)
                    /v1/tools/execute (execute tool)
```

Unlike MCP which uses persistent connections, Shepherd integration uses stateless HTTP requests.

## Shepherd API

### GET /v1/tools
Lists available tools.

**Response:**
```json
{
  "tools": [
    {
      "name": "bash",
      "description": "Execute shell commands",
      "parameters": {
        "type": "object",
        "properties": {
          "command": {"type": "string", "description": "Command to execute"}
        },
        "required": ["command"]
      }
    }
  ]
}
```

### POST /v1/tools/execute
Executes a tool.

**Request:**
```json
{
  "name": "bash",
  "arguments": {"command": "whoami"},
  "tool_call_id": "shepherd_bash_abc123"
}
```

**Response:**
```json
{
  "tool_call_id": "shepherd_bash_abc123",
  "success": true,
  "content": "steve"
}
```

**Error Response:**
```json
{
  "tool_call_id": "shepherd_bash_abc123",
  "success": false,
  "content": "",
  "error": "Command failed with exit code 1"
}
```

## Configuration

Add a Shepherd tool server via Admin Settings:

1. Go to **Admin Panel** → **Settings** → **Tool Servers**
2. Click **Add Connection**
3. Configure:
   - **Type**: shepherd
   - **URL**: http://localhost:8000 (Shepherd API server URL)
   - **Auth Type**: bearer (recommended)
   - **API Key**: Your Shepherd API key
   - **Name**: Shepherd Tools (display name)
   - **Description**: Tools from Shepherd (optional)

## ShepherdClient Class

Located in `backend/open_webui/utils/shepherd/client.py`.

```python
class ShepherdClient:
    async def connect(url: str, headers: dict = None)
        # Store connection info (no persistent connection)

    async def list_tool_specs() -> List[dict]
        # GET /v1/tools

    async def call_tool(name: str, args: dict) -> List[dict]
        # POST /v1/tools/execute

    async def disconnect()
        # No-op (HTTP is stateless)
```

MCPClient-compatible API for consistency.

## Integration Points

### Tool Loading (middleware.py)
- Handles `server:shepherd:{server_id}` tool_ids
- Creates ShepherdClient, fetches tools, creates callables
- Merges into tools_dict

### Tool Listing (routers/tools.py)
- Filters TOOL_SERVER_CONNECTIONS by type="shepherd"
- Returns ToolUserResponse with proper id format

### Verification (routers/configs.py)
- Creates ShepherdClient
- Calls list_tool_specs() to verify connection
- Returns tool specs on success

## Authentication

Supported auth types:
- `none`: No authentication header
- `bearer`: `Authorization: Bearer {api_key}`
- `session`: Uses user's session token
- `system_oauth`: Uses system OAuth token

## vs MCP Proxy

This direct integration vs using an MCP proxy:

| Aspect | Direct (Shepherd type) | MCP Proxy |
|--------|----------------------|-----------|
| Setup | One-click in admin | Separate process |
| Connection | Stateless HTTP | Persistent MCP |
| Latency | Lower (direct) | Higher (extra hop) |
| Complexity | Simpler | More moving parts |
| Flexibility | Shepherd-specific | MCP-compatible |

## Files

| File | Purpose |
|------|---------|
| `utils/shepherd/__init__.py` | Module exports |
| `utils/shepherd/client.py` | ShepherdClient class |
| `utils/shepherd/shepherd.md` | This documentation |
| `utils/middleware.py` | Tool loading integration |
| `routers/tools.py` | Tool listing integration |
| `routers/configs.py` | Verification endpoint |

## Version History

- **v1.0.0** - Initial implementation with tool list/execute support
