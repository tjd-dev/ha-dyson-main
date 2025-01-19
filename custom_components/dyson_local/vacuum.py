"""Vacuum platform for Dyson."""
from typing import Any, Optional

from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DATA_DEVICES, DOMAIN
from . import DysonEntity

SUPPORT_DYSON_360 = (
    VacuumEntityFeature.START |
    VacuumEntityFeature.PAUSE |
    VacuumEntityFeature.RETURN_HOME |
    VacuumEntityFeature.STATUS |
    VacuumEntityFeature.BATTERY |
    VacuumEntityFeature.STATE
)

async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities
) -> None:
    """Set up Dyson vacuum from a config entry."""
    device = hass.data[DOMAIN][config_entry.entry_id][DATA_DEVICES]
    async_add_entities([DysonVacuumEntity(device)])

class DysonVacuumEntity(DysonEntity, StateVacuumEntity):
    """Dyson vacuum entity."""

    _attr_supported_features = SUPPORT_DYSON_360

    @property
    def state(self) -> str:
        """Return the state of the vacuum."""
        return self._device.state.value

    @property
    def battery_level(self) -> Optional[int]:
        """Return the battery level of the vacuum."""
        return self._device.battery_level

    async def async_start(self) -> None:
        """Start cleaning."""
        await self.hass.async_add_executor_job(self._device.start)

    async def async_pause(self) -> None:
        """Pause cleaning."""
        await self.hass.async_add_executor_job(self._device.pause)

    async def async_return_to_base(self) -> None:
        """Return to base."""
        await self.hass.async_add_executor_job(self._device.return_to_base)
