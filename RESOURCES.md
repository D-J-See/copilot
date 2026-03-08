# MCP Dynamic Resources

This MCP server now supports dynamic resources in addition to tools. Resources provide read-only access to server-managed data that can be queried via the MCP protocol.

## Architecture

### ResourceRegistry Class

Similar to `ToolRegistry`, there is now a `ResourceRegistry` class that:
- Registers resource handlers via `@registry.register()` decorator
- Discovers resources in the tools directory (same auto-discovery as tools)
- Provides `resources/list` and `resources/read` JSON-RPC methods

### Key Differences from Tools

| Aspect | Tools | Resources |
|--------|-------|-----------|
| Purpose | Actions/functions that perform work | Read-only data/state that's queried |
| Parameters | Accept input arguments | No parameters |
| Return Type | Any (JSON serialized) | String (may contain JSON) |
| Use Cases | Execute operations | Provide data inventories |

## Creating Custom Resources

### 1. Register resources in tools directory

Create or edit a file in `mcp/tools/` with a `register_resources()` function:

```python
def register_resources(registry: "ResourceRegistry") -> None:
    @registry.register(
        name="my-resource",
        description="Description of what this resource provides",
        mime_type="application/json",  # optional, defaults to text/plain
    )
    def get_my_resource() -> str:
        # Return string (can be JSON)
        data = {"key": "value"}
        return json.dumps(data, indent=2)
```

### 2. Key Parameters

- **name**: Unique resource identifier (used in URI as `resource://name`)
- **description**: Human-readable description
- **mime_type**: Content type (e.g., `"application/json"`, `"text/plain"`, `"text/yaml"`)

### 3. Load from Data Sources

Resources can dynamically load from:
- YAML/JSON config files
- REST APIs
- Database queries
- Command-line tools
- File systems
- Registry queries

## Built-in Resources

The example `resources.py` demonstrates four resources:

### 1. `packages/versions`
**Description**: JSON list of packages and firmware with tracked versions

Query via MCP:
```
GET resource://packages/versions
```

Returns JSON with package information including current version, latest version, and update availability.

### 2. `devices/esphome`
**Description**: ESPHome devices inventory with firmware versions

Query via MCP:
```
GET resource://devices/esphome
```

Returns all ESPHome devices with:
- Device name and friendly name
- IP address
- Current firmware version
- Latest available version
- Update availability status
- Platform (esp32, esp8266, etc.)

### 3. `devices/esphome/upgradeable`
**Description**: Filtered list of ESPHome devices needing updates

Query via MCP:
```
GET resource://devices/esphome/upgradeable
```

Returns only devices that have firmware updates available.

### 4. `deployment/manifest`
**Description**: System deployment manifest with component versions

Query via MCP:
```
GET resource://deployment/manifest
```

Returns deployment info with all component versions and operational status.

## Request/Response Format

### List Resources

**Request:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "resources/list"
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "resources": [
      {
        "uri": "resource://packages/versions",
        "name": "packages/versions",
        "description": "JSON list of packages and firmware with tracked versions",
        "mimeType": "application/json"
      },
      ...
    ]
  }
}
```

### Read Resource

**Request:**
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "resources/read",
  "params": {
    "uri": "resource://devices/esphome"
  }
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "contents": [
      {
        "uri": "resource://devices/esphome",
        "mimeType": "application/json",
        "text": "{ ... JSON content ... }"
      }
    ]
  }
}
```

## Use Case: ESPHome Device Upgrades

To upgrade ESPHome on various devices:

1. **Query available devices:**
   - Call `resources/read` with `resource://devices/esphome/upgradeable`
   - Get list of devices needing updates

2. **Trigger update tool (future enhancement):**
   ```python
   @registry.register(name="esphome/upgrade_device")
   def upgrade_esphome(device_name: str, target_version: str) -> str:
       # Implementation to upgrade specific device
       return json.dumps({"status": "upgrading"})
   ```

3. **Check status:**
   - Query `resource://devices/esphome` to see updated versions

## Integration with VS Code / GitHub Copilot

Resources are now advertised in server capabilities:

```json
"capabilities": {
  "tools": {"listChanged": true},
  "resources": {"listChanged": true}
}
```

This enables VS Code extensions and GitHub Copilot to:
- Discover available resources on server startup
- Query resource data for context
- Provide resource information to AI models for decision-making

## Server Output

When starting the server, you'll see:

```
MCP server  http://localhost:8080  (5 tools, 4 resources)
Tools:     check_port, dns_lookup, get_current_time, get_environment_variable, ...
Resources: deployment/manifest, devices/esphome, devices/esphome/upgradeable, packages/versions
```

## Adding Your Own Resources

1. Create or edit `mcp/tools/resources.py` (or any `.py` file in `mcp/tools/`)
2. Add a `register_resources()` function
3. Use the `@registry.register()` decorator
4. Restart the server
5. Resources are automatically discovered and registered

Resources are loaded the same way as tools via the auto-discovery system—no manual registration needed!
