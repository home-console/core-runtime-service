# Marketplace Module

Dynamic plugin installation and lifecycle management for HomeConsole OS.

## Features

- **Plugin Installation**: Install plugins from ZIP/TAR archives without core restart
- **Manifest Validation**: Validate plugin.json schema and plugin naming conventions
- **Security**: SHA256 validation, path traversal detection, name collision prevention
- **Dynamic Loading**: Load and register plugin capabilities at runtime via PluginManager
- **Lifecycle Management**: Enable/disable/update plugins with full storage integration
- **Operation Routing**: All operations exposed via operations subsystem for capability routing

## Architecture

### Components

1. **MarketplaceInstaller** (`installer.py`)
   - Extract ZIP/TAR archives
   - Validate plugins.json manifest
   - Calculate and verify SHA256 hashes
   - Move plugins to `plugins/` directory
   - Integrate with PluginManager for dynamic loading

2. **MarketplaceService** (`services.py`)
   - Implement operation handlers (install, remove, update, enable, disable, list_installed)
   - Manage plugin storage in `marketplace.installed` namespace
   - Return standardized operation results

3. **MarketplaceModule** (`module.py`)
   - RuntimeModule extending HomeConsole core
   - Register all marketplace operations with OperationManager
   - Track installed plugins in storage
   - Provide marketplace capability metadata

### Storage Model

```python
namespace: marketplace.installed
{
  "plugin_name": {
    "name": str,
    "version": str,
    "path": str,
    "hash": str,
    "entrypoint": str,
    "installed_at": datetime.isoformat(),
    "enabled": bool,
    "capabilities_provided": List[str],
    "capabilities_required": List[str],
  }
}
```

### Operations

All operations are exposed through the operations subsystem:

- `marketplace.install` - Install plugin from archive
- `marketplace.remove` - Remove installed plugin
- `marketplace.update` - Update plugin to new version
- `marketplace.enable` - Enable disabled plugin
- `marketplace.disable` - Disable plugin without removing
- `marketplace.list_installed` - List all installed plugins

## Usage Example

```python
# Install plugin from archive
operation = Operation(
    operation_id="install_123",
    op_type="marketplace.install",
    params={
        "archive_path": "/path/to/plugin.zip",
        "sha256": "optional_hash"  # Optional
    },
    initiator=OperationInitiator(kind=OperationInitiatorKind.ADMIN)
)

result = await runtime.operations.execute(operation)
# Returns: {
#   "status": "success",
#   "data": {
#     "name": "my_plugin",
#     "version": "1.0.0",
#     "path": "/Users/misha/HomeConsole/plugins/my_plugin",
#     "installed_at": "2024-01-01T12:00:00.000000",
#     "hash": "abc123...",
#     "entrypoint": "plugin.py",
#     "capabilities_provided": ["custom.feature"]
#   }
# }
```

## Plugin Format

### Directory Structure

```
my-plugin/
├── plugin.json          # Plugin manifest (required)
├── plugin.py            # Plugin entrypoint (or other module)
├── __init__.py          # Package marker
├── src/                 # Additional modules
└── requirements.txt     # Optional dependencies
```

### plugin.json Schema

```json
{
  "name": "my_plugin",                          // Required: snake_case
  "version": "1.0.0",                           // Required: semver
  "description": "My custom plugin",            // Required
  "author": "Your Name",                        // Required
  "entrypoint": "plugin.py",                    // Required
  "capabilities_provided": ["custom.feature"],  // Optional
  "capabilities_required": ["core.storage"],    // Optional
  "dependencies": []                            // Optional
}
```

### plugin.py Example

```python
from sdk.plugin_ext import BasePlugin


class MyPlugin(BasePlugin):
    def metadata(self):
        return {
            "name": "my_plugin",
            "version": "1.0.0"
        }

    async def on_load(self):
        """Initialize plugin on load."""
        print("Plugin loaded!")

    async def on_start(self):
        """Execute on runtime start."""
        print("Plugin started!")

    async def on_stop(self):
        """Cleanup on runtime stop."""
        print("Plugin stopped!")

    def list_capabilities(self):
        """List capabilities provided by this plugin."""
        return ["custom.feature"]
```

## Security Features

### Path Traversal Prevention
- Validates plugin_name matches `^[a-z_][a-z0-9_]*$`
- Blocks "../" and "\" in paths
- Validates entrypoint exists within plugin directory

### Hash Verification
- SHA256 validation of archive integrity
- Optional pre-verified hash parameter
- Prevents tampering and ensures reproducibility

### Conflict Detection
- Prevents duplicate plugin installation
- Detects version mismatches on update
- Validates manifest format before extraction

### Capability Isolation
- Each plugin registers capabilities independently
- CapabilityRegistry tracks required/provided capabilities
- Runtime validates dependency resolution

## Testing

Comprehensive test suite with 26 tests covering:

- ✅ Valid plugin installation from ZIP/TAR
- ✅ SHA256 validation and mismatch detection
- ✅ Plugin manifest validation and schema enforcement
- ✅ Duplicate installation prevention
- ✅ Dynamic plugin loading via PluginManager
- ✅ Uninstallation and capability cleanup
- ✅ Update operations with version management
- ✅ Enable/disable state transitions
- ✅ Storage integration and persistence
- ✅ Error handling and recovery

Run tests:
```bash
pytest tests/test_marketplace_module.py -v
```

## Integration Points

### PluginManager
- `load_plugin(instance)` - Load plugin at runtime
- `start_plugin(name)` - Start plugin and activate capabilities
- `stop_plugin(name)` - Stop plugin gracefully
- `unload_plugin(name)` - Remove plugin from registry

### CapabilityRegistry
- `register_provider(module, capability)` - Register capabilities
- `get_providers(capability_id)` - List providers for capability
- `validate_plugin_requirements(plugin)` - Check dependencies

### Storage
- `marketplace.installed` - Track installed plugins
- Persistent storage ensures plugins survive core restart
- No core restart required for installation/removal

### Operations Subsystem
- All operations are first-class Operation entities
- Full audit trail and operation lifecycle
- Capability-based routing via operations registry

## No Core Restart Required

Key achievement: **Dynamic plugin installation without core restart**

- `PluginManager.load_plugin()` loads at runtime
- `CapabilityRegistry.register_provider()` auto-updates
- `Storage` persists plugin metadata
- `OperationManager` routes to handlers without restart

## Known Limitations

- Plugins must follow BasePlugin interface
- Manifest must be `plugin.json` in archive root
- Entrypoint must be Python module
- Dependencies not automatically installed (manual pip install if needed)
- Plugin updates don't preserve plugin state (would need migration)

## Future Enhancements

- [ ] Remote marketplace server for plugin discovery
- [ ] Plugin dependency resolution and auto-install
- [ ] Plugin versioning and rollback
- [ ] Marketplace Inspector endpoint (/admin/v1/inspector/marketplace)
- [ ] Plugin signing and verification
- [ ] Automated plugin health monitoring
- [ ] Plugin metrics and logging
