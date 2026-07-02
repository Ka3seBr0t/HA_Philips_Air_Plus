"""Constants for the Philips Air+ integration."""
from __future__ import annotations

from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfTime,
)

DOMAIN = "philips_airplus"

# Config entry data keys
CONF_USER_ID = "user_id"  # the OneID/gaoda user id (hex), PHILIPS:<user_id> is the signing username
CONF_MSECRET = "msecret"  # gaoda HMAC signing secret, extracted from the user's own APK
CONF_EMAIL = "email"  # Philips account email (display only; user_id is what's used at runtime)
CONF_DEVICES = "devices"  # optional explicit device ids; auto-discovered if absent

# Defaults / limits
JWT_REFRESH_MARGIN = 24 * 3600  # refresh the 7-day JWT when <1 day remains

# ---- D-code property map (verified against CX3550/01 "Fan1" 2026-06-27) ----
# Shadow reported/desired codes. See notes/properties.md §3e.
D_POWER = "D03102"        # power flag  0=off / 1=on
D_SPEED = "D0310D"        # fan level   0..3  (manual speed)
D_MODE = "D0310C"         # mode preset 1/2/3=stufe, 17=sleep, 130=natural (echoes -126)
D_OSCILLATE = "D0320F"    # oscillation 23040=on / 0=off
D_BEEP = "D03130"         # key-beep    0=off / 100=on
D_TIMER_ACT = "D03110"    # timer active 0=off / 2=on
D_TIMER_MIN = "D03211"    # timer remaining minutes (READ-ONLY countdown)

# Device meta codes (reported only)
D_NAME = "D01S03"
D_TYPE = "D01S04"
D_MODEL = "D01S05"
D_SERIAL = "D01S0D"
D_SWVERSION = "D01S12"
D_RSSI = "rssi"
D_RUNTIME = "Runtime"
D_FREE_MEMORY = "free_memory"
D_CONNECT_TYPE = "ConnectType"

# Oscillation: the device REPORTS 23040 (=0x5A00 = 90<<8) when swinging and 0
# when still, but to TURN IT ON you must WRITE the angle in degrees (90). Writing
# 23040 is rejected (reported snaps back to 0). 0 writes to off. Read = != 0.
OSC_ON_WRITE = 90
OSC_OFF = 0
OSC_ON_REPORTED = 23040  # read-back value when oscillating (90 deg)
BEEP_ON = 100
BEEP_OFF = 0
TIMER_ON = 2
TIMER_OFF = 0

# Mode presets (D0310C). CX3550 has NO turbo.
MODE_SLEEP = 17
MODE_NATURAL = 130
PRESET_SLEEP = "sleep"
PRESET_NATURAL = "natural"
PRESET_MODES = [PRESET_SLEEP, PRESET_NATURAL]
PRESET_TO_MODE = {PRESET_SLEEP: MODE_SLEEP, PRESET_NATURAL: MODE_NATURAL}
MODE_TO_PRESET = {MODE_SLEEP: PRESET_SLEEP, MODE_NATURAL: PRESET_NATURAL}

# Manual speed steps (1/2/3) mapped to HA percentage with speed_count=3.
SPEED_COUNT = 3
# ordered_list_step default HA gives [33, 67, 100] for 3 speeds; level = round(pct/100*3)

# MQTT shadow topics
TOPIC_GET = "$aws/things/{thing}/shadow/get"
TOPIC_GET_ACCEPTED = "$aws/things/{thing}/shadow/get/accepted"
TOPIC_GET_REJECTED = "$aws/things/{thing}/shadow/get/rejected"
TOPIC_UPDATE = "$aws/things/{thing}/shadow/update"
TOPIC_UPDATE_ACCEPTED = "$aws/things/{thing}/shadow/update/accepted"
TOPIC_UPDATE_REJECTED = "$aws/things/{thing}/shadow/update/rejected"
TOPIC_UPDATE_DOCUMENTS = "$aws/things/{thing}/shadow/update/documents"

# Manufacturer / model
MANUFACTURER = "Philips"
MODEL_CX3550 = "CX3550/01"

# Reconnect backoff (seconds)
RECONNECT_MIN = 2
RECONNECT_MAX = 300

# Sensor native units
UNIT_TIMER_MIN = UnitOfTime.MINUTES
UNIT_SIGNAL = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
UNIT_DURATION = UnitOfTime.SECONDS

__all__ = [
    "DOMAIN", "CONF_USER_ID", "CONF_MSECRET", "CONF_EMAIL", "CONF_DEVICES", "JWT_REFRESH_MARGIN",
    "D_POWER", "D_SPEED", "D_MODE", "D_OSCILLATE", "D_BEEP",
    "D_TIMER_ACT", "D_TIMER_MIN",
    "D_NAME", "D_TYPE", "D_MODEL", "D_SERIAL", "D_SWVERSION",
    "D_RSSI", "D_RUNTIME", "D_FREE_MEMORY", "D_CONNECT_TYPE",
    "OSC_ON_WRITE", "OSC_OFF", "OSC_ON_REPORTED", "BEEP_ON", "BEEP_OFF", "TIMER_ON", "TIMER_OFF",
    "MODE_SLEEP", "MODE_NATURAL", "PRESET_SLEEP", "PRESET_NATURAL",
    "PRESET_MODES", "PRESET_TO_MODE", "MODE_TO_PRESET",
    "SPEED_COUNT",
    "TOPIC_GET", "TOPIC_GET_ACCEPTED", "TOPIC_GET_REJECTED",
    "TOPIC_UPDATE", "TOPIC_UPDATE_ACCEPTED", "TOPIC_UPDATE_REJECTED",
    "TOPIC_UPDATE_DOCUMENTS",
    "MANUFACTURER", "MODEL_CX3550",
    "RECONNECT_MIN", "RECONNECT_MAX",
    "UNIT_TIMER_MIN", "UNIT_SIGNAL", "UNIT_DURATION",
]