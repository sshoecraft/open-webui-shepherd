"""
Secret resolution for fetching secrets from external vaults.

Supports:
- Azure Key Vault: URLs matching *.vault.azure.net/secrets/*
- HashiCorp Vault via Unix socket: unix:///path/to/socket#/v1/secret/data/key
"""

import json
import logging
import os
import re
import socket

log = logging.getLogger(__name__)

AZURE_KEYVAULT_PATTERN = re.compile(
    r'^https://[\w-]+\.vault\.azure\.net/secrets/([\w-]+)(?:/([\w-]+))?$'
)
HASHICORP_UNIX_PATTERN = re.compile(r'^unix://([^#]+)#(.+)$')


class SecretResolutionError(Exception):
    """Raised when a secret cannot be resolved from a vault."""
    pass


def resolve_secret(value: str) -> str:
    """
    Resolve a secret from a vault if the value matches a known pattern.
    Returns the original value unchanged if not a vault URL.
    """
    if not value or not isinstance(value, str):
        return value

    if '.vault.azure.net/secrets/' in value:
        return _resolve_azure_keyvault(value)

    if value.startswith('unix://'):
        return _resolve_hashicorp_unix(value)

    return value


def _resolve_azure_keyvault(url: str) -> str:
    """Fetch secret from Azure Key Vault using Managed Identity."""
    try:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient
    except ImportError as e:
        raise SecretResolutionError(
            "azure-keyvault-secrets not installed"
        ) from e

    match = AZURE_KEYVAULT_PATTERN.match(url)
    if not match:
        raise SecretResolutionError(f"Invalid Azure Key Vault URL: {url}")

    secret_name = match.group(1)
    secret_version = match.group(2)
    vault_url = url.split('/secrets/')[0]

    log.info(f"Resolving secret '{secret_name}' from {vault_url}")

    try:
        credential = DefaultAzureCredential()
        client = SecretClient(vault_url=vault_url, credential=credential)
        secret = client.get_secret(secret_name, version=secret_version)
        log.info(f"Successfully resolved secret '{secret_name}'")
        return secret.value
    except Exception as e:
        raise SecretResolutionError(f"Failed to fetch from Azure Key Vault: {e}") from e


def _resolve_hashicorp_unix(url: str) -> str:
    """Fetch secret from HashiCorp Vault via Unix socket."""
    match = HASHICORP_UNIX_PATTERN.match(url)
    if not match:
        raise SecretResolutionError(f"Invalid HashiCorp Vault URL: {url}")

    socket_path = match.group(1)
    vault_path = match.group(2)

    if not os.path.exists(socket_path):
        raise SecretResolutionError(f"Unix socket not found: {socket_path}")

    log.info(f"Resolving secret from Vault via {socket_path}")

    try:
        request = f"GET {vault_path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(30)
        sock.connect(socket_path)
        sock.sendall(request.encode('utf-8'))

        response = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk
        sock.close()

        response_str = response.decode('utf-8')
        headers_end = response_str.find('\r\n\r\n')
        if headers_end == -1:
            raise SecretResolutionError("Invalid HTTP response from Vault")

        status_line = response_str.split('\r\n')[0]
        if '200' not in status_line:
            raise SecretResolutionError(f"Vault error: {status_line}")

        body = response_str[headers_end + 4:]
        data = json.loads(body)

        # KV v2 structure: data.data.value
        if 'data' in data and 'data' in data['data']:
            secret_data = data['data']['data']
            if 'value' in secret_data:
                return secret_data['value']
            if secret_data:
                return next(iter(secret_data.values()))

        # KV v1 structure: data.value
        if 'data' in data:
            secret_data = data['data']
            if 'value' in secret_data:
                return secret_data['value']
            if secret_data:
                return next(iter(secret_data.values()))

        raise SecretResolutionError("Could not extract secret value from response")

    except SecretResolutionError:
        raise
    except Exception as e:
        raise SecretResolutionError(f"Failed to fetch from HashiCorp Vault: {e}") from e
