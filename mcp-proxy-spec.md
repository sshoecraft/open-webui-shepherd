# MCP Proxy for Shepherd Tools

## Overview

Create an MCP server that acts as a proxy to Shepherd's tool execution API. This allows any MCP-compatible client (like Open Web UI) to use Shepherd's tools without modification.

## Architecture

```
Open Web UI  ──MCP Protocol──►  MCP Proxy  ──HTTP──►  Shepherd API Server
                                                      /v1/tools
                                                      /v1/tools/execute
```

## What the MCP Proxy Does

1. **On Startup**: Connect to Shepherd, fetch available tools
2. **Expose Tools via MCP**: Register each tool with MCP protocol
3. **On Tool Call**: Proxy execution request to Shepherd, return result

## Shepherd API Endpoints

### GET /v1/tools
Returns list of available tools for the authenticated API key.

**Request:**
```
GET /v1/tools
Authorization: Bearer <api_key>
```

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
    },
    {
      "name": "read_file",
      "description": "Read contents of a file",
      "parameters": {
        "type": "object",
        "properties": {
          "path": {"type": "string", "description": "Path to file"}
        },
        "required": ["path"]
      }
    }
  ]
}
```

### POST /v1/tools/execute
Execute a tool and return the result.

**Request:**
```
POST /v1/tools/execute
Authorization: Bearer <api_key>
Content-Type: application/json

{
  "name": "bash",
  "arguments": {"command": "whoami"},
  "tool_call_id": "tc_123"
}
```

**Response:**
```json
{
  "tool_call_id": "tc_123",
  "success": true,
  "content": "steve"
}
```

**Error Response:**
```json
{
  "tool_call_id": "tc_123",
  "success": false,
  "content": "",
  "error": "Command failed with exit code 1"
}
```

## MCP Proxy Implementation

### Configuration

```yaml
# config.yaml or environment variables
shepherd:
  url: "http://localhost:8000"  # Shepherd API server URL
  api_key: "sk-..."             # API key for authentication
```

Or via environment:
```
SHEPHERD_URL=http://localhost:8000
SHEPHERD_API_KEY=sk-...
```

### Startup Flow

1. Read configuration (URL, API key)
2. Call `GET /v1/tools` to fetch available tools
3. For each tool, register it with MCP:
   - Name: tool.name
   - Description: tool.description
   - Input Schema: tool.parameters (already in JSON Schema format)

### Tool Execution Flow

When MCP client calls a tool:

1. Receive tool call from MCP client:
   - Tool name
   - Arguments (dict/object)
   - Call ID (generate if not provided)

2. POST to Shepherd:
   ```json
   {
     "name": "<tool_name>",
     "arguments": <arguments_object>,
     "tool_call_id": "<call_id>"
   }
   ```

3. Return result to MCP client:
   - If success: return content as tool result
   - If error: return error message as tool result (or raise MCP error)

### Refresh/Reconnect

Optionally implement:
- Periodic refresh of tool list (tools might change)
- Reconnect logic if Shepherd restarts
- Health check endpoint

## Python Implementation Sketch

Using the MCP Python SDK:

```python
import os
import httpx
from mcp.server import Server
from mcp.types import Tool, TextContent

SHEPHERD_URL = os.environ.get("SHEPHERD_URL", "http://localhost:8000")
SHEPHERD_API_KEY = os.environ.get("SHEPHERD_API_KEY", "")

server = Server("shepherd-tools")
http_client = httpx.Client(
    base_url=SHEPHERD_URL,
    headers={"Authorization": f"Bearer {SHEPHERD_API_KEY}"}
)

# Fetch tools from Shepherd
def fetch_tools():
    response = http_client.get("/v1/tools")
    response.raise_for_status()
    return response.json()["tools"]

# Register tools with MCP
@server.list_tools()
async def list_tools():
    tools = fetch_tools()
    return [
        Tool(
            name=t["name"],
            description=t.get("description", ""),
            inputSchema=t.get("parameters", {"type": "object", "properties": {}})
        )
        for t in tools
    ]

# Handle tool execution
@server.call_tool()
async def call_tool(name: str, arguments: dict):
    response = http_client.post("/v1/tools/execute", json={
        "name": name,
        "arguments": arguments,
        "tool_call_id": f"mcp_{name}_{id(arguments)}"
    })
    response.raise_for_status()
    result = response.json()

    if result.get("success", True):
        return [TextContent(type="text", text=result["content"])]
    else:
        return [TextContent(type="text", text=f"Error: {result.get('error', 'Unknown error')}")]

# Run server
if __name__ == "__main__":
    import mcp.server.stdio
    mcp.server.stdio.run(server)
```

## Node.js Implementation Sketch

Using the MCP TypeScript SDK:

```typescript
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

const SHEPHERD_URL = process.env.SHEPHERD_URL || "http://localhost:8000";
const SHEPHERD_API_KEY = process.env.SHEPHERD_API_KEY || "";

const server = new Server({ name: "shepherd-tools", version: "1.0.0" }, {
  capabilities: { tools: {} }
});

async function fetchTools() {
  const response = await fetch(`${SHEPHERD_URL}/v1/tools`, {
    headers: { "Authorization": `Bearer ${SHEPHERD_API_KEY}` }
  });
  const data = await response.json();
  return data.tools;
}

server.setRequestHandler("tools/list", async () => {
  const tools = await fetchTools();
  return {
    tools: tools.map(t => ({
      name: t.name,
      description: t.description || "",
      inputSchema: t.parameters || { type: "object", properties: {} }
    }))
  };
});

server.setRequestHandler("tools/call", async (request) => {
  const { name, arguments: args } = request.params;

  const response = await fetch(`${SHEPHERD_URL}/v1/tools/execute`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${SHEPHERD_API_KEY}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      name,
      arguments: args,
      tool_call_id: `mcp_${name}_${Date.now()}`
    })
  });

  const result = await response.json();

  return {
    content: [{
      type: "text",
      text: result.success ? result.content : `Error: ${result.error}`
    }]
  };
});

const transport = new StdioServerTransport();
server.connect(transport);
```

## Testing

1. Start Shepherd API server:
   ```
   shepherd --provider llama-gpt-oss --apiserver
   ```

2. Create API key (if auth enabled):
   ```
   shepherd apikey create test
   ```

3. Test endpoints manually:
   ```bash
   # List tools
   curl http://localhost:8000/v1/tools -H "Authorization: Bearer <key>"

   # Execute tool
   curl -X POST http://localhost:8000/v1/tools/execute \
     -H "Authorization: Bearer <key>" \
     -H "Content-Type: application/json" \
     -d '{"name":"bash","arguments":{"command":"whoami"}}'
   ```

4. Run MCP proxy:
   ```
   SHEPHERD_URL=http://localhost:8000 SHEPHERD_API_KEY=<key> python mcp_proxy.py
   ```

5. Configure Open Web UI to use the MCP server

## Open Web UI Integration

In Open Web UI's MCP configuration, add the shepherd-tools server:

```json
{
  "mcpServers": {
    "shepherd-tools": {
      "command": "python",
      "args": ["/path/to/mcp_proxy.py"],
      "env": {
        "SHEPHERD_URL": "http://localhost:8000",
        "SHEPHERD_API_KEY": "sk-..."
      }
    }
  }
}
```

Or if running as a separate service, configure the connection accordingly.
