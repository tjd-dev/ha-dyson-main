"""Support for Dyson devices."""

import asyncio
from datetime import timedelta
from functools import partial
import logging
from typing import List, Optional

from .vendor.libdyson import (
    Dyson360Eye,
    Dyson360Heurist,
    Dyson360VisNav,
    DysonPureHotCool,
    DysonPureHotCoolLink,
    DysonPurifierHumidifyCool,
    MessageType,
    get_device,
)
from .vendor.libdyson.cloud import (
    DysonAccountCN,
    DysonAccount,
)
from .vendor.libdyson.discovery import DysonDiscovery
from .vendor.libdyson.dyson_device import DysonDevice
from .vendor.libdyson.exceptions import (
    DysonException,
    DysonNetworkError,
    DysonLoginFailure,
)

from homeassistant.components.zeroconf import async_get_instance
from homeassistant.config_entries import ConfigEntry, SOURCE_DISCOVERY
from homeassistant.const import CONF_HOST, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_CREDENTIAL,
    CONF_DEVICE_TYPE,
    CONF_SERIAL,
    DATA_COORDINATORS,
    DATA_DEVICES,
    DATA_DISCOVERY,
    DOMAIN,
)

from .cloud.const import (
    CONF_REGION,
    CONF_AUTH,
    DATA_ACCOUNT,
    DATA_DEVICES,
)

_LOGGER = logging.getLogger(__name__)

ENVIRONMENTAL_DATA_UPDATE_INTERVAL = timedelta(seconds=30)

PLATFORMS = ["camera"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up Dyson integration."""
    hass.data[DOMAIN] = {
        DATA_DEVICES: {},
        DATA_COORDINATORS: {},
        DATA_DISCOVERY: None,
    }
    return True


async def async_setup_account(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a MyDyson Account."""
    if entry.data[CONF_REGION] == "CN":
        account = DysonAccountCN(entry.data[CONF_AUTH])
    else:
        account = DysonAccount(entry.data[CONF_AUTH])

    try:
        devices = await hass.async_add_executor_job(account.devices)

        for index, device in enumerate(devices):
            try:
                iot_detail = await hass.async_add_executor_job(
                    account.get_iot_details, device.serial
                )
                _LOGGER.debug("IoT details for device %s: %s", device.serial, iot_detail)

                devices[index] = device.with_iot_details({
                    "client_id": iot_detail["IoTCredentials"]["ClientId"],
                    "endpoint": iot_detail["Endpoint"],
                    "token_value": iot_detail["IoTCredentials"]["TokenValue"],
                    "token_signature": iot_detail["IoTCredentials"]["TokenSignature"],
                })
            except DysonNetworkError as err:
                _LOGGER.error("Failed to fetch IoT details for device %s: %s", device.serial, err)

    except DysonNetworkError as err:
        _LOGGER.error("Cannot connect to Dyson cloud service: %s", err)
        raise ConfigEntryNotReady

    for device in devices:
        _LOGGER.debug("Device to initialize config flow: %s (%s)", device, type(device))
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_DISCOVERY},
                data=device,
            )
        )
        _LOGGER.debug("Flow created for device: %s", device.serial)


    hass.data[DOMAIN][entry.entry_id] = {
        DATA_ACCOUNT: account,
        DATA_DEVICES: devices,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Dyson from a config entry."""
    device_type = entry.data[CONF_DEVICE_TYPE]
    serial = entry.data[CONF_SERIAL]
    credential = entry.data[CONF_CREDENTIAL]
    name = entry.data[CONF_NAME]
    
    # Create device instance
    device = get_device(serial, credential, device_type)
    if device is None:
        _LOGGER.error("Unsupported device type: %s", device_type)
        return False

    try:
        # For 360 Vis Nav, skip local discovery and go straight to IoT connection
        if device_type == "277":  # 277 is the product_type for Vis Nav
            if "iot_details" not in entry.data:
                raise ConfigEntryNotReady("IoT credentials required for Vis Nav")
                
            iot_info = entry.data["iot_details"]
            _LOGGER.debug(
                "Setting up remote connection for Vis Nav device %s",
                serial
            )
            try:
                await hass.async_add_executor_job(
                    device.connect,
                    iot_info["Endpoint"],  # host
                    8883,  # port
                    iot_info["IoTCredentials"]["ClientId"],  # username
                    iot_info["IoTCredentials"]["TokenValue"],  # password
                    {
                        "x-amzn-iot-token": iot_info["IoTCredentials"]["TokenSignature"]
                    },  # headers
                    True,  # tls
                )
                _LOGGER.info("Successfully connected to Vis Nav %s via IoT", serial)
            except DysonException as err:
                _LOGGER.error(
                    "Failed to connect to Vis Nav %s via IoT: %s",
                    serial,
                    err,
                )
                raise ConfigEntryNotReady("Failed to connect to device")
        else:
            # Original local discovery code for other devices
            discovery = DysonDiscovery()
            await hass.async_add_executor_job(discovery.start_discovery)
            connected = False
            
            def _callback(address: str):
                """Set up connection using discovered address."""
                nonlocal connected
                try:
                    device.connect(address)
                    connected = True
                except DysonException as err:
                    _LOGGER.debug("Failed to connect to device %s: %s", address, err)

            await hass.async_add_executor_job(
                discovery.register_device, device, _callback
            )
            
            # If local discovery fails and we have IoT details, try remote connection
            if not connected and "iot_details" in entry.data:
                iot_info = entry.data["iot_details"]
                _LOGGER.debug(
                    "Local discovery failed. Attempting remote connection for device %s",
                    serial
                )
                try:
                    await hass.async_add_executor_job(
                        device.connect,
                        iot_info["Endpoint"],  # host
                        8883,  # port
                        iot_info["IoTCredentials"]["ClientId"],  # username
                        iot_info["IoTCredentials"]["TokenValue"],  # password
                        {
                            "x-amzn-iot-token": iot_info["IoTCredentials"]["TokenSignature"]
                        },  # headers
                        True,  # tls
                    )
                    connected = True
                    _LOGGER.info("Successfully connected to device %s via IoT", serial)
                except DysonException as err:
                    _LOGGER.error(
                        "Failed to connect to device %s via IoT: %s",
                        serial,
                        err,
                    )
                    raise ConfigEntryNotReady("Failed to connect to device")

            if not connected:
                raise ConfigEntryNotReady("Device not found")

        # Store device for platforms to set up
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][entry.entry_id] = {
            DATA_DEVICES: device,
        }

        # Set up platforms
        await hass.config_entries.async_forward_entry_setups(
            entry, ["vacuum", "sensor"]
        )

        return True

    except DysonException as err:
        _LOGGER.error("Failed to connect to device %s: %s", serial, err)
        raise ConfigEntryNotReady("Failed to connect to device") from err


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Dyson local."""
    device: DysonDevice = hass.data[DOMAIN][DATA_DEVICES][entry.entry_id]

    unload_ok = await hass.config_entries.async_unload_platforms(entry, _async_get_platforms(device))

    if unload_ok:
        hass.data[DOMAIN][DATA_DEVICES].pop(entry.entry_id)
        hass.data[DOMAIN][DATA_COORDINATORS].pop(entry.entry_id)
        await hass.async_add_executor_job(device.disconnect)
        # TODO: stop discovery
    return unload_ok


@callback
def _async_get_platforms(device: DysonDevice) -> List[str]:
    if (isinstance(device, Dyson360Eye)
            or isinstance(device, Dyson360Heurist)
            or isinstance(device, Dyson360VisNav)):
        return ["binary_sensor", "sensor", "vacuum"]
    platforms = ["fan", "select", "sensor", "switch"]
    if isinstance(device, DysonPureHotCool):
        platforms.append("climate")
    if isinstance(device, DysonPureHotCoolLink):
        platforms.extend(["binary_sensor", "climate"])
    if isinstance(device, DysonPurifierHumidifyCool):
        platforms.append("humidifier")
    if hasattr(device, "filter_life") or hasattr(device, "carbon_filter_life") or hasattr(device, "hepa_filter_life"):
        platforms.append("button")
    return platforms


class DysonEntity(Entity):
    """Dyson entity base class."""

    _MESSAGE_TYPE = MessageType.STATE

    def __init__(self, device: DysonDevice, name: str):
        """Initialize the entity."""
        self._device = device
        self._name = name

    async def async_added_to_hass(self) -> None:
        """Call when entity is added to hass."""
        self._device.add_message_listener(self._on_message)

    def _on_message(self, message_type: MessageType) -> None:
        if self._MESSAGE_TYPE is None or message_type == self._MESSAGE_TYPE:
            self.schedule_update_ha_state()

    @property
    def should_poll(self) -> bool:
        """No polling needed."""
        return False

    @property
    def name(self) -> str:
        """Return the name of the entity."""
        if self.sub_name is None:
            return self._name
        return f"{self._name} {self.sub_name}"

    @property
    def sub_name(self) -> Optional[str]:
        """Return sub name of the entity."""
        return None

    @property
    def unique_id(self) -> str:
        """Return the entity unique id."""
        if self.sub_unique_id is None:
            return self._device.serial
        return f"{self._device.serial}-{self.sub_unique_id}"

    @property
    def sub_unique_id(self) -> str:
        """Return the entity sub unique id."""
        return None

    @property
    def device_info(self) -> dict:
        """Return device info of the entity."""
        return {
            "identifiers": {(DOMAIN, self._device.serial)},
            "name": self._name,
            "manufacturer": "Dyson",
            "model": self._device.device_type,
        }
