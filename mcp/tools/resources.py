"""
Example auto-discovered resources module.
==========================================
This file is loaded automatically because it lives in the tools/ directory
and exposes a  register_resources(registry)  function.

To add a resource: add another @registry.register block inside register_resources().
All resources should return strings (which may contain JSON).

Resources provide read-only access to server state — perfect for:
- Package/firmware version catalogs
- Device inventories and status
- Configuration data
- System metrics snapshots
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server import ResourceRegistry


def register_resources(registry: "ResourceRegistry") -> None:
    """Called by the server's auto-discovery on startup."""

    # ── Package and firmware version tracking ──────────────────────────

    # This is sample data — in production, load from a real source:
    # - YAML config file
    # - REST API call to a package server
    # - Database query
    # - Docker registry API
    # etc.

    PACKAGES_WITH_VERSIONS = {
        "packages": [
            {
                "name": "esphome",
                "type": "firmware-builder",
                "current_version": "2025.1.3",
                "latest_version": "2025.2.0",
                "tracked": True,
                "update_available": True,
            },
            {
                "name": "python",
                "type": "runtime",
                "current_version": "3.11.8",
                "latest_version": "3.12.1",
                "tracked": True,
                "update_available": True,
            },
            {
                "name": "docker",
                "type": "container-engine",
                "current_version": "25.0.1",
                "latest_version": "25.0.2",
                "tracked": True,
                "update_available": True,
            },
            {
                "name": "node",
                "type": "runtime",
                "current_version": "20.10.0",
                "latest_version": "20.11.0",
                "tracked": True,
                "update_available": True,
            },
            {
                "name": "postgresql",
                "type": "database",
                "current_version": "15.3",
                "latest_version": "16.1",
                "tracked": True,
                "update_available": True,
            },
        ]
    }

    @registry.register(
        name="packages/versions",
        description="JSON list of packages and firmware with tracked versions",
        mime_type="application/json",
    )
    def get_packages_with_versions() -> str:
        """Return JSON of all packages with version tracking."""
        return json.dumps(PACKAGES_WITH_VERSIONS, indent=2)

    # ── ESPHome devices inventory ──────────────────────────────────────

    # Sample ESPHome devices — in production load from:
    # - ESPHome YAML configs directory
    # - Home Assistant REST API
    # - Configuration database
    # - Device discovery scan
    # etc.

    ESPHOME_DEVICES = {
        "devices": [
            {
                "name": "bedroom-motion-sensor",
                "friendly_name": "Bedroom Motion Sensor",
                "ip_address": "192.168.1.101",
                "firmware_version": "2024.12.1",
                "latest_version": "2025.2.0",
                "update_available": True,
                "platform": "esp32",
                "last_updated": "2025-03-08T10:30:00Z",
            },
            {
                "name": "kitchen-lights",
                "friendly_name": "Kitchen Lights",
                "ip_address": "192.168.1.102",
                "firmware_version": "2025.1.2",
                "latest_version": "2025.2.0",
                "update_available": True,
                "platform": "esp8266",
                "last_updated": "2025-03-07T15:45:00Z",
            },
            {
                "name": "living-room-temp",
                "friendly_name": "Living Room Temperature",
                "ip_address": "192.168.1.103",
                "firmware_version": "2025.2.0",
                "latest_version": "2025.2.0",
                "update_available": False,
                "platform": "esp32",
                "last_updated": "2025-03-08T09:00:00Z",
            },
            {
                "name": "garage-door",
                "friendly_name": "Garage Door",
                "ip_address": "192.168.1.104",
                "firmware_version": "2024.11.3",
                "latest_version": "2025.2.0",
                "update_available": True,
                "platform": "esp32-c3",
                "last_updated": "2025-02-28T12:15:00Z",
            },
            {
                "name": "hallway-lights",
                "friendly_name": "Hallway Lights",
                "ip_address": "192.168.1.105",
                "firmware_version": "2025.1.0",
                "latest_version": "2025.2.0",
                "update_available": True,
                "platform": "esp8266",
                "last_updated": "2025-03-01T08:30:00Z",
            },
        ],
        "metadata": {
            "total": 5,
            "upgradeable": 4,
            "updated": "2025-03-08T11:00:00Z",
        },
    }

    @registry.register(
        name="devices/esphome",
        description="ESPHome devices inventory with current and available firmware versions",
        mime_type="application/json",
    )
    def get_esphome_devices() -> str:
        """Return JSON of all ESPHome devices and their versions."""
        return json.dumps(ESPHOME_DEVICES, indent=2)

    # ── Devices needing updates ────────────────────────────────────────

    @registry.register(
        name="devices/esphome/upgradeable",
        description="ESPHome devices that have firmware updates available",
        mime_type="application/json",
    )
    def get_upgradeable_esphome_devices() -> str:
        """Return JSON of ESPHome devices that need updates."""
        upgradeable = [
            d for d in ESPHOME_DEVICES["devices"] if d["update_available"]
        ]
        return json.dumps(
            {
                "devices": upgradeable,
                "count": len(upgradeable),
                "timestamp": "2025-03-08T11:00:00Z",
            },
            indent=2,
        )

    # ── System deployment manifest ────────────────────────────────────

    DEPLOYMENT_MANIFEST = {
        "deployment": {
            "environment": "production",
            "timestamp": "2025-03-08T11:00:00Z",
            "components": [
                {
                    "name": "esphome",
                    "version": "2025.1.3",
                    "devices_count": 5,
                    "status": "operational",
                },
                {
                    "name": "home-assistant",
                    "version": "2025.3.0",
                    "status": "operational",
                },
                {
                    "name": "postgresql-db",
                    "version": "15.3",
                    "status": "operational",
                },
                {
                    "name": "mqtt-broker",
                    "version": "5.0.0",
                    "status": "operational",
                },
            ],
            "updates_pending": 4,
            "health": "good",
        }
    }

    @registry.register(
        name="deployment/manifest",
        description="System deployment manifest with component versions and status",
        mime_type="application/json",
    )
    def get_deployment_manifest() -> str:
        """Return JSON deployment manifest."""
        return json.dumps(DEPLOYMENT_MANIFEST, indent=2)
