"""Sensor platform for Philips Air+ (CX3550/01).

  * timer_remaining   D03211  minutes (read-only countdown of the auto-off timer)
  * rssi              rssi    dBm   (DIAGNOSTIC, disabled by default)
  * runtime           Runtime seconds (DIAGNOSTIC, disabled by default)
  * free_memory       free_memory bytes (DIAGNOSTIC, disabled by default)

The timer countdown (D03211) is **read-only**: writing it is ignored by the
device (it sets the value itself when the timer is activated via D03110). So
it is exposed as a sensor, not a Number.
"""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfInformation,
    UnitOfTemperature,
    UnitOfTime,
)

try:
    from homeassistant.const import UnitOfDensity, UnitOfRatio

    _UNIT_PM25 = UnitOfDensity.MICROGRAMS_PER_CUBIC_METER
    _UNIT_PERCENT = UnitOfRatio.PERCENTAGE
except ImportError:  # Compatibility with Home Assistant versions before 2026.7.
    from homeassistant.const import (
        CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        PERCENTAGE,
    )

    _UNIT_PM25 = CONCENTRATION_MICROGRAMS_PER_CUBIC_METER
    _UNIT_PERCENT = PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    D_FREE_MEMORY,
    D_GAS_INDEX,
    D_HUMIDITY,
    D_IAI,
    D_PM25,
    D_RSSI,
    D_RUNTIME,
    D_TEMPERATURE,
    D_TIMER_MIN,
    DOMAIN,
    MANUFACTURER,
    MODEL_CX3550,
    MODEL_AC3360,
)
from .coordinator import PhilipsAirplusCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    store = hass.data[DOMAIN][entry.entry_id]
    for coordinator in store["coordinators"].values():
        entities = [
            PhilipsAirplusRssiSensor(coordinator),
            PhilipsAirplusRuntimeSensor(coordinator),
            PhilipsAirplusFreeMemorySensor(coordinator),
        ]
        if (coordinator.device_info or {}).get("modelid") != MODEL_AC3360:
            entities.append(PhilipsAirplusTimerRemaining(coordinator))
        else:
            entities.extend(
                [
                    PhilipsAirplusPM25Sensor(coordinator),
                    PhilipsAirplusAllergenIndexSensor(coordinator),
                    PhilipsAirplusGasIndexSensor(coordinator),
                    PhilipsAirplusTemperatureSensor(coordinator),
                    PhilipsAirplusHumiditySensor(coordinator),
                ]
            )
        async_add_entities(entities)


class _AirplusSensor(CoordinatorEntity, SensorEntity):
    """Common base."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PhilipsAirplusCoordinator) -> None:
        super().__init__(coordinator)
        self.coordinator = coordinator

    @property
    def device_info(self) -> DeviceInfo:
        di = self.coordinator.device_info or {}
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.device_id)},
            name=di.get("name") or di.get("device_alias"),
            manufacturer=MANUFACTURER,
            model=di.get("modelid") or MODEL_CX3550,
            sw_version=di.get("swversion"),
            serial_number=di.get("mac"),
        )

    @property
    def available(self) -> bool:
        return self.coordinator.device_available

    def _rep(self) -> dict:
        return self.coordinator.data or {}

    def _num(self, code: str):
        try:
            return int(self._rep().get(code))
        except (TypeError, ValueError):
            return None


class PhilipsAirplusTimerRemaining(_AirplusSensor):
    """Remaining minutes of the auto-off timer (D03211, read-only countdown)."""

    _attr_translation_key = "timer_remaining"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: PhilipsAirplusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_timer_remaining"

    @property
    def native_value(self):
        return self._num(D_TIMER_MIN)


class PhilipsAirplusRssiSensor(_AirplusSensor):
    """WiFi signal strength (rssi, dBm)."""

    _attr_translation_key = "rssi"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: PhilipsAirplusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_rssi"

    @property
    def native_value(self):
        return self._num(D_RSSI)


class PhilipsAirplusRuntimeSensor(_AirplusSensor):
    """Device uptime (Runtime, seconds)."""

    _attr_translation_key = "runtime"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: PhilipsAirplusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_runtime"

    @property
    def native_value(self):
        return self._num(D_RUNTIME)


class PhilipsAirplusFreeMemorySensor(_AirplusSensor):
    """Free heap memory (free_memory, bytes)."""

    _attr_translation_key = "free_memory"
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_native_unit_of_measurement = UnitOfInformation.BYTES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: PhilipsAirplusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_free_memory"

    @property
    def native_value(self):
        return self._num(D_FREE_MEMORY)


class PhilipsAirplusPM25Sensor(_AirplusSensor):
    """PM2.5 concentration in µg/m³ (D03221)."""

    _attr_translation_key = "pm25"
    _attr_device_class = SensorDeviceClass.PM25
    _attr_native_unit_of_measurement = _UNIT_PM25
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: PhilipsAirplusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_pm25"

    @property
    def native_value(self):
        return self._num(D_PM25)


class PhilipsAirplusAllergenIndexSensor(_AirplusSensor):
    """Unitless allergen index / IAI (D03120)."""

    _attr_translation_key = "allergen_index"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: PhilipsAirplusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_allergen_index"

    @property
    def native_value(self):
        return self._num(D_IAI)


class PhilipsAirplusGasIndexSensor(_AirplusSensor):
    """Raw, unitless gas index (D03122); only raw 1 is verified as L1."""

    _attr_translation_key = "gas_index"

    def __init__(self, coordinator: PhilipsAirplusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_gas_index"

    @property
    def raw_value(self) -> int | None:
        """Keep the device's numeric level available without reinterpretation."""
        return self._num(D_GAS_INDEX)

    @property
    def extra_state_attributes(self) -> dict[str, int] | None:
        raw = self.raw_value
        return None if raw is None else {"raw_value": raw}

    @property
    def native_value(self):
        raw = self.raw_value
        return "L1" if raw == 1 else raw


class PhilipsAirplusTemperatureSensor(_AirplusSensor):
    """Ambient temperature (D03224, tenths of a degree Celsius)."""

    _attr_translation_key = "temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: PhilipsAirplusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_temperature"

    @property
    def native_value(self) -> float | None:
        raw = self._num(D_TEMPERATURE)
        return None if raw is None else raw / 10


class PhilipsAirplusHumiditySensor(_AirplusSensor):
    """Relative humidity percentage (D03125)."""

    _attr_translation_key = "humidity"
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_native_unit_of_measurement = _UNIT_PERCENT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: PhilipsAirplusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_humidity"

    @property
    def native_value(self):
        return self._num(D_HUMIDITY)
