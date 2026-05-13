# OpenCode MCP Configuration

Below is the successfully configured `mcp.json` structure for OpenCode:

```json
{
  "mcpServers": {
    "email": {
      "command": "py",
      "args": [
        "-3.9",
        "C:\\Users\\joung\\slsi-cowork-plugins\\email-mcp\\server.py"
      ],
      "env": {
        "EMAIL_CONNECTOR_PATH": "C:\\Users\\joung\\slsi-cowork-plugins\\email-connector"
      }
    }
  }
}
```

## Setup Notes
- Python 3.9 64-bit is required.
- The `email-connector` directory must be fully configured (dependencies installed, `.env` file present with `EMBEDDING_API_URL` and `PST_PATH` set).
