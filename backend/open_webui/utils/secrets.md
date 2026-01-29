# secrets.py - External Secret Resolution

## Purpose

Resolves `DATABASE_URL` from external secret stores at startup, enabling secure credential management without storing secrets in environment variables.

## Supported Backends

### Azure Key Vault
- **Pattern**: `https://<vault>.vault.azure.net/secrets/<secret-name>[/<version>]`
- **Auth**: Managed Identity (MSI) via `DefaultAzureCredential`
- **Dependencies**: `azure-identity`, `azure-keyvault-secrets`

### HashiCorp Vault (Unix Socket)
- **Pattern**: `unix:///path/to/socket#/v1/secret/data/<path>`
- **Auth**: Vault Agent handles auth, app connects via socket
- **Dependencies**: None (uses stdlib `socket`)

## Architecture

```
DATABASE_URL env var
        │
        ▼
 resolve_secret()
        │
        ├─► Azure Key Vault URL? ──► _resolve_azure_keyvault() ──► MSI auth
        │
        ├─► Unix socket URL? ──► _resolve_hashicorp_unix() ──► Socket HTTP
        │
        └─► Neither? ──► Return unchanged
        │
        ▼
Actual connection string
```

## Integration Point

Called from `env.py` after `DATABASE_URL` is constructed (line ~293).

## Error Handling

- `SecretResolutionError` raised on any failure
- App exits on failure (no silent fallback to vault URL as connection string)

## Usage Examples

```bash
# Azure Key Vault
DATABASE_URL="https://myvault.vault.azure.net/secrets/db-connection"

# HashiCorp Vault via Unix socket
DATABASE_URL="unix:///var/run/vault.sock#/v1/secret/data/database"

# Plain (unchanged)
DATABASE_URL="postgresql://user:pass@host:5432/db"
```

## History

- 2026-01-28: Initial implementation (Azure Key Vault + HashiCorp Unix socket)
