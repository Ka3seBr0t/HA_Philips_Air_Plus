"""Fan platform for Philips Air+ devices.

Maps the verified D-code shadow state to a Home Assistant fan entity:

  on/off          D03102   power flag 0/1
  speed / mode    model-specific D0310D and/or D0310C
  preset_mode     CX3550 only: D0310C 17=sleep, 130=natural
  oscillate       CX3550 only: D0320F 23040=on / 0=off

CX3550 exposes manual speeds as percentages and its sleep/natural presets.
AC3360 exposes all eight named D0310C modes as fan presets and maps a fine
percentage slider to the same reported modes.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    D_MODE,
    D_OSCILLATE,
    D_POWER,
    D_SPEED,
    AC3360_PERCENTAGE_TO_MODE,
    MANUFACTURER,
    MODEL_AC3360,
    MODEL_CX3550,
    OSC_OFF,
    OSC_ON_WRITE,
    SPEED_COUNT,
    get_model_capabilities,
    is_ac3360_device,
)
from .coordinator import PhilipsAirplusCoordinator

_LOGGER = logging.getLogger(__name__)

# Manual speed level <-> HA percentage (speed_count=3 -> [33, 67, 100]).
_LEVEL_TO_PCT = {0: 0, 1: 33, 2: 67, 3: 100}
_PCT_TO_LEVEL = {33: 1, 67: 2, 100: 3}


def _pct_to_level(pct: int) -> int:
    if pct <= 0:
        return 0
    return round(pct / 100 * SPEED_COUNT)


def _norm_mode(v, *, safe_overflow: bool = False) -> int | None:
    """D0310C may echo as a signed byte (130 -> -126); normalize to unsigned."""
    try:
        return int(v) & 0xFF
    except (TypeError, ValueError):
        return None
    except OverflowError:
        if safe_overflow:
            return None
        raise


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    store = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        PhilipsAirplusFan(coordinator) for coordinator in store["coordinators"].values()
    )


class PhilipsAirplusFan(CoordinatorEntity, FanEntity):
    """A Philips Air+ fan with capabilities selected by model."""

    _attr_has_entity_name = True
    _attr_name = None  # use the device name
    _attr_speed_count = None

    def __init__(self, coordinator: PhilipsAirplusCoordinator) -> None:
        device_info = coordinator.device_info or {}
        capabilities = get_model_capabilities(
            device_info.get("modelid"), device_info.get("type")
        )
        is_ac3360 = is_ac3360_device(device_info)
        # Set before CoordinatorEntity initialization so a cached HA property
        # can never observe a default/None value for AC3360.
        if is_ac3360:
            self._attr_speed_count = 100
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._capabilities = capabilities
        self._attr_translation_key = self._capabilities["translation_key"]
        self._attr_preset_modes = self._capabilities["preset_modes"]
        if not is_ac3360:
            self._attr_speed_count = self._capabilities.get("speed_count")
        self._attr_unique_id = f"{coordinator.device_id}_fan"
        self._attr_supported_features = _supported_features(self._capabilities)
        if is_ac3360:
            _LOGGER.debug(
                "AC3360 fan %s initialized (modelid=%r, type=%r, speed_count=%s, percentage_step=%s)",
                coordinator.device_id,
                device_info.get("modelid"),
                device_info.get("type"),
                self.speed_count,
                self.percentage_step,
            )

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

    # ---- state ----
    def _rep(self) -> dict:
        return self.coordinator.data or {}

    @property
    def is_on(self) -> bool:
        if not self._is_ac3360:
            return int(self._rep().get(D_POWER, 0)) == 1
        try:
            return int(self._rep().get(D_POWER, 0)) == 1
        except (TypeError, ValueError, OverflowError):
            return False

    @property
    def percentage(self) -> int | None:
        rep = self._rep()
        if not self._is_ac3360:
            if int(rep.get(D_POWER, 0)) != 1:
                return 0
            if not self._capabilities["percentage_control"]:
                return None
            try:
                return _LEVEL_TO_PCT.get(int(rep.get(D_SPEED)), None)
            except (TypeError, ValueError):
                return None
        try:
            is_on = int(rep.get(D_POWER, 0)) == 1
        except (TypeError, ValueError, OverflowError):
            is_on = False
        if not is_on:
            return 0
        mode_to_percentage = self._capabilities.get("mode_to_percentage")
        if mode_to_percentage is not None:
            mode = _norm_mode(rep.get(D_MODE), safe_overflow=True)
            return mode_to_percentage.get(mode)
        if not self._capabilities["percentage_control"]:
            return None
        level = rep.get(D_SPEED)
        try:
            return _LEVEL_TO_PCT.get(int(level), None)
        except (TypeError, ValueError):
            return None

    @property
    def preset_mode(self) -> str | None:
        mode = _norm_mode(
            self._rep().get(D_MODE), safe_overflow=self._is_ac3360
        )
        return self._capabilities["mode_to_preset"].get(mode)

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        mode_names = self._capabilities.get("mode_names")
        if mode_names is None:
            return None
        mode = _norm_mode(
            self._rep().get(D_MODE), safe_overflow=self._is_ac3360
        )
        name = mode_names.get(mode)
        return {"current_mode_name": name} if name is not None else None

    @property
    def oscillating(self) -> bool:
        try:
            return int(self._rep().get(D_OSCILLATE, 0)) != 0
        except (TypeError, ValueError):
            return False

    # ---- commands ----
    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        desired: dict = {D_POWER: 1}
        preset_to_mode = self._capabilities["preset_to_mode"]
        if self._is_ac3360:
            if preset_mode in preset_to_mode:
                desired[D_MODE] = preset_to_mode[preset_mode]
            elif percentage is not None:
                mode = _ac3360_percentage_to_mode(percentage)
                if mode is None:
                    desired = {D_POWER: 0}
                else:
                    desired[D_MODE] = mode
            else:
                current_mode = _norm_mode(
                    self._rep().get(D_MODE), safe_overflow=True
                )
                if current_mode not in self._capabilities["mode_names"]:
                    desired[D_MODE] = 0
            await self.coordinator.async_set_desired(desired)
            return
        if preset_mode in preset_to_mode:
            desired[D_MODE] = preset_to_mode[preset_mode]
        elif percentage is not None and self._capabilities["percentage_control"]:
            level = _pct_to_level(percentage)
            if level > 0:
                desired[D_SPEED] = level
                desired[D_MODE] = level  # manual mode mirrors the level
            desired[D_POWER] = 1 if level > 0 else 0
        await self.coordinator.async_set_desired(desired)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_desired({D_POWER: 0})

    async def async_set_percentage(self, percentage: int) -> None:
        if not self._capabilities["percentage_control"]:
            return
        if self._is_ac3360:
            mode = _ac3360_percentage_to_mode(percentage)
            if mode is None:
                await self.coordinator.async_set_desired({D_POWER: 0})
            else:
                await self.coordinator.async_set_desired({D_POWER: 1, D_MODE: mode})
            return
        level = _pct_to_level(percentage)
        desired: dict = {D_SPEED: level, D_MODE: level, D_POWER: 1 if level > 0 else 0}
        await self.coordinator.async_set_desired(desired)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        preset_to_mode = self._capabilities["preset_to_mode"]
        if preset_mode not in preset_to_mode:
            return
        await self.coordinator.async_set_desired(
            {D_POWER: 1, D_MODE: preset_to_mode[preset_mode]}
        )

    @property
    def _is_ac3360(self) -> bool:
        return self._capabilities.get("mode_to_percentage") is not None

    async def async_oscillate(self, oscillating: bool) -> None:
        if not self._capabilities["oscillation"]:
            return
        await self.coordinator.async_set_desired(
            {D_OSCILLATE: OSC_ON_WRITE if oscillating else OSC_OFF}
        )


def _ac3360_percentage_to_mode(percentage: int) -> int | None:
    """Map a slider value to the nearest canonical AC3360 mode; zero is off."""
    try:
        pct = max(0, min(100, int(percentage)))
    except (TypeError, ValueError):
        return None
    if pct == 0:
        return None
    # On ties, choose the higher slider point.
    return min(AC3360_PERCENTAGE_TO_MODE, key=lambda item: (abs(item[0] - pct), -item[0]))[1]


def _supported_features(capabilities: dict) -> FanEntityFeature:
    """Build fan features from the selected model capabilities."""
    features = FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
    if capabilities["percentage_control"]:
        features |= FanEntityFeature.SET_SPEED
    if capabilities["preset_modes"]:
        features |= FanEntityFeature.PRESET_MODE
    if capabilities["oscillation"]:
        features |= FanEntityFeature.OSCILLATE
    return features
