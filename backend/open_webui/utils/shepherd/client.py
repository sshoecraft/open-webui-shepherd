"""
Shepherd Tool API Client.
HTTP client for Shepherd's /v1/tools and /v1/tools/execute endpoints.
"""
import logging
import uuid
from typing import Optional, Dict, Any, List

import aiohttp

from open_webui.env import AIOHTTP_CLIENT_TIMEOUT

log = logging.getLogger(__name__)


class ShepherdClient:
    """
    HTTP client for Shepherd's tool API.

    Unlike MCPClient which uses persistent MCP connections, ShepherdClient
    uses stateless HTTP requests. This is simpler and sufficient since
    Shepherd's tool API is RESTful.

    API compatibility with MCPClient:
    - connect(url, headers) - store connection info
    - list_tool_specs() - returns list of tool specs
    - call_tool(name, args) - executes tool and returns result
    - disconnect() - no-op for HTTP
    """

    def __init__(self):
        self.url: Optional[str] = None
        self.headers: Optional[Dict[str, str]] = None

    async def connect(self, url: str, headers: Optional[Dict[str, str]] = None):
        """
        Store connection parameters.

        No persistent connection needed for HTTP - we just store the URL
        and headers for use in subsequent requests.

        :param url: Base URL of the Shepherd API server (e.g., http://localhost:8000)
        :param headers: Optional headers (e.g., {"Authorization": "Bearer ..."})
        """
        self.url = url.rstrip('/')
        self.headers = headers or {}
        log.debug(f"ShepherdClient configured for {self.url}")

    async def list_tool_specs(self) -> List[Dict[str, Any]]:
        """
        Fetch available tools from Shepherd API.

        Calls GET /v1/tools and returns the tools list normalized to match
        the format expected by Open WebUI's middleware.

        :return: List of tool specs with name, description, parameters
        :raises RuntimeError: If client is not connected
        :raises Exception: On HTTP errors or invalid responses
        """
        if not self.url:
            raise RuntimeError("ShepherdClient is not connected. Call connect() first.")

        request_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            **self.headers,
        }

        async with aiohttp.ClientSession(
            trust_env=True,
            timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT),
        ) as session:
            async with session.get(
                f"{self.url}/v1/tools",
                headers=request_headers,
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    log.error(f"Failed to fetch tools from Shepherd: {response.status} - {error_text}")
                    raise Exception(f"Failed to fetch tools: HTTP {response.status}")

                data = await response.json()
                tools = data.get("tools", [])

                # Normalize to match MCPClient output format
                tool_specs = []
                for tool in tools:
                    tool_specs.append({
                        "name": tool.get("name"),
                        "description": tool.get("description", ""),
                        "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
                    })

                log.debug(f"Fetched {len(tool_specs)} tools from Shepherd")
                return tool_specs

    async def call_tool(
        self, function_name: str, function_args: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Execute a tool via Shepherd API.

        Calls POST /v1/tools/execute with the tool name and arguments.

        :param function_name: Name of the tool to execute
        :param function_args: Arguments to pass to the tool
        :return: Tool execution result as list of content blocks (MCP format)
        :raises RuntimeError: If client is not connected
        :raises Exception: On HTTP errors or tool execution failure
        """
        if not self.url:
            raise RuntimeError("ShepherdClient is not connected. Call connect() first.")

        request_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            **self.headers,
        }

        # Generate unique tool_call_id
        tool_call_id = f"shepherd_{function_name}_{uuid.uuid4().hex[:8]}"

        payload = {
            "name": function_name,
            "arguments": function_args,
            "tool_call_id": tool_call_id,
        }

        log.debug(f"Executing Shepherd tool: {function_name} with args: {function_args}")

        async with aiohttp.ClientSession(
            trust_env=True,
            timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT),
        ) as session:
            async with session.post(
                f"{self.url}/v1/tools/execute",
                headers=request_headers,
                json=payload,
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    log.error(f"Tool execution failed: {response.status} - {error_text}")
                    raise Exception(f"Tool execution failed: HTTP {response.status}")

                result = await response.json()

                if not result.get("success", True):
                    error_msg = result.get("error", "Unknown error")
                    log.error(f"Tool {function_name} failed: {error_msg}")
                    raise Exception(error_msg)

                content = result.get("content", "")
                log.debug(f"Tool {function_name} completed successfully")

                # Return in MCP-compatible format (list of content blocks)
                # This format is expected by Open WebUI's middleware
                return [{"type": "text", "text": content}]

    async def disconnect(self):
        """
        Disconnect from Shepherd.

        No-op for HTTP client since there's no persistent connection.
        Included for API compatibility with MCPClient.
        """
        log.debug("ShepherdClient disconnect (no-op for HTTP)")
        pass

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()
        return False
