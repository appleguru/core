"""Common code for tplink."""
from __future__ import annotations

import logging
from typing import Callable

from pyHS100 import (
    Discover,
    SmartBulb,
    SmartDevice,
    SmartDeviceException,
    SmartPlug,
    SmartStrip,
)

from homeassistant.core import HomeAssistant

from .const import DOMAIN as TPLINK_DOMAIN

_LOGGER = logging.getLogger(__name__)


ATTR_CONFIG = "config"
CONF_DIMMER = "dimmer"
CONF_DISCOVERY = "discovery"
CONF_LIGHT = "light"
CONF_STRIP = "strip"
CONF_SWITCH = "switch"
MAX_DISCOVERY_RETRIES = 4


class SmartDevices:
    """Hold different kinds of devices."""

    def __init__(
        self, lights: list[SmartDevice] = None, switches: list[SmartDevice] = None
    ) -> None:
        """Initialize device holder."""
        self._lights = lights or []
        self._switches = switches or []

    @property
    def lights(self) -> list[SmartDevice]:
        """Get the lights."""
        return self._lights

    @property
    def switches(self) -> list[SmartDevice]:
        """Get the switches."""
        return self._switches

    def has_device_with_host(self, host: str) -> bool:
        """Check if a devices exists with a specific host."""
        for device in self.lights + self.switches:
            if device.host == host:
                return True

        return False


async def async_get_discoverable_devices(hass: HomeAssistant) -> dict[str, SmartDevice]:
    """Return if there are devices that can be discovered."""

    def discover() -> dict[str, SmartDevice]:
        return Discover.discover()

    return await hass.async_add_executor_job(discover)


async def async_discover_devices(
    hass: HomeAssistant, existing_devices: SmartDevices, target_device_count: int
) -> SmartDevices:
    """Get devices through discovery."""

    lights = []
    switches = []

    def process_devices() -> None:
        for dev in devices.values():
            # If this device already exists, ignore dynamic setup.
            if existing_devices.has_device_with_host(dev.host):
                continue

            if isinstance(dev, SmartStrip):
                for plug in dev.plugs.values():
                    switches.append(plug)
            elif isinstance(dev, SmartPlug):
                try:
                    if dev.is_dimmable:  # Dimmers act as lights
                        lights.append(dev)
                    else:
                        switches.append(dev)
                except SmartDeviceException as ex:
                    _LOGGER.error("Unable to connect to device %s: %s", dev.host, ex)

            elif isinstance(dev, SmartBulb):
                lights.append(dev)
            else:
                _LOGGER.error("Unknown smart device type: %s", type(dev))

    devices = dict()
    for attempt in range(1, MAX_DISCOVERY_RETRIES + 1):
        _LOGGER.debug(
            "Discovering tplink devices, attempt %s of %s",
            attempt,
            MAX_DISCOVERY_RETRIES,
        )
        discovered_devices = await async_get_discoverable_devices(hass)
        _LOGGER.info(
            "Discovered %s TP-Link of expected %s smart home device(s)",
            len(discovered_devices),
            target_device_count,
        )
        for ip in discovered_devices:
            devices[ip] = discovered_devices[ip]

        if len(discovered_devices) >= target_device_count:
            _LOGGER.info(
                "Discovered at least as many devices on the network as exist in our device registry, no need to retry"
            )
            break

    _LOGGER.info(
        "Found %s unique TP-Link smart home device(s) after %s discovery attempts",
        len(devices),
        attempt,
    )
    await hass.async_add_executor_job(process_devices)

    return SmartDevices(lights, switches)


def get_static_devices(config_data) -> SmartDevices:
    """Get statically defined devices in the config."""
    _LOGGER.debug("Getting static devices")
    lights = []
    switches = []

    for type_ in [CONF_LIGHT, CONF_SWITCH, CONF_STRIP, CONF_DIMMER]:
        for entry in config_data[type_]:
            host = entry["host"]
            try:
                if type_ == CONF_LIGHT:
                    lights.append(SmartBulb(host))
                elif type_ == CONF_SWITCH:
                    switches.append(SmartPlug(host))
                elif type_ == CONF_STRIP:
                    for plug in SmartStrip(host).plugs.values():
                        switches.append(plug)
                # Dimmers need to be defined as smart plugs to work correctly.
                elif type_ == CONF_DIMMER:
                    lights.append(SmartPlug(host))
            except SmartDeviceException as sde:
                _LOGGER.error(
                    "Failed to setup device %s due to %s; not retrying", host, sde
                )
    return SmartDevices(lights, switches)


def add_available_devices(
    hass: HomeAssistant, device_type: str, device_class: Callable
) -> list:
    """Get sysinfo for all devices."""

    devices = hass.data[TPLINK_DOMAIN][device_type]

    if f"{device_type}_remaining" in hass.data[TPLINK_DOMAIN]:
        devices = hass.data[TPLINK_DOMAIN][f"{device_type}_remaining"]

    entities_ready = []
    devices_unavailable = []
    for device in devices:
        try:
            device.get_sysinfo()
            entities_ready.append(device_class(device))
        except SmartDeviceException as ex:
            devices_unavailable.append(device)
            _LOGGER.warning(
                "Unable to communicate with device %s: %s",
                device.host,
                ex,
            )

    hass.data[TPLINK_DOMAIN][f"{device_type}_remaining"] = devices_unavailable
    return entities_ready
