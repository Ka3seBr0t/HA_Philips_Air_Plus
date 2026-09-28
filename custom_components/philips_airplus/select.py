"""Model-specific select entities for Philips Air+ devices."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    D_DISPLAY,
    DOMAIN,
    MANUFACTURER,
    MODEL_AC3360,
    MODEL_CX3550,
    is_ac3360_device,
)
from .coordinator import PhilipsAirplusCoordinator

_BRIGHTNESS_TO_CODE = {"off": 0, "low": 115, "bright": 123}
_CODE_TO_BRIGHTNESS = {code: name for name, code in _BRIGHTNESS_TO_CODE.items()}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    store = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        PhilipsAirplusDisplayBrightness(coordinator)
        for coordinator in store["coordinators"].values()
        if is_ac3360_device(coordinator.device_info)
    )


class PhilipsAirplusDisplayBrightness(CoordinatorEntity, SelectEntity):
    """AC3360 display brightness selector (D03105)."""

    _attr_has_entity_name = True
    _attr_translation_key = "display_brightness"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(_BRIGHTNESS_TO_CODE)

    def __init__(self, coordinator: PhilipsAirplusCoordinator) -> None:
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._attr_unique_id = f"{coordinator.device_id}_display_brightness"

    @property
    def device_info(self) -> DeviceInfo:
        di = self.coordinator.device_info or {}
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.device_id)},
            name=di.get("name") or di.get("device_alias"),
            manufacturer=MANUFACTURER,
            model=(
                MODEL_AC3360
                if is_ac3360_device(di)
                else di.get("modelid") or MODEL_CX3550
            ),
            sw_version=di.get("swversion"),
            serial_number=di.get("mac"),
        )

    @property
    def available(self) -> bool:
        return self.coordinator.device_available

    @property
    def current_option(self) -> str | None:
        try:
            code = int((self.coordinator.data or {}).get(D_DISPLAY))
        except (TypeError, ValueError, OverflowError):
            return None
        return _CODE_TO_BRIGHTNESS.get(code)

    async def async_select_option(self, option: str) -> None:
        if option in _BRIGHTNESS_TO_CODE:
            await self.coordinator.async_set_desired(
                {D_DISPLAY: _BRIGHTNESS_TO_CODE[option]}
            )
