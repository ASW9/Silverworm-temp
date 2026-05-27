"""
Hardware transport factory.

Reads hw_platform from AppConfig, looks up the matching PlatformConfig
in hw_config.py, and constructs the correct I2C/SPI transport objects.

Python opens Linux device files (/dev/i2c-N, /dev/spidev-B.D).
The actual GPIO→peripheral mux is set by the OS — see hw_config.py for
the physical pin table and bring-up notes.

Optional SPI1 bus (if two SPI buses are needed in future):
  SPI1 MOSI  GPIO20  pin 38
  SPI1 MISO  GPIO19  pin 35
  SPI1 SCLK  GPIO21  pin 40
  SPI1 CE0   GPIO18  pin 12
  (requires dtoverlay=spi1-1cs in /boot/firmware/config.txt)
"""

from __future__ import annotations

from dataclasses import dataclass

from config import AppConfig
from comms.pui import PUITransport, MockPUITransport, I2CPUITransport
from comms.motor_spi import SPITransport, MockSPITransport, SPIMotorTransport
from hw_config import get_platform


@dataclass
class Transports:
    """Bundle of transports returned by build_transports()."""
    pui: PUITransport
    wrap_spi: SPITransport
    feed_spi: SPITransport
    is_mock: bool


def build_transports(config: AppConfig) -> Transports:
    """
    Construct PUI + motor SPI transports for the configured hw_platform.

    "mock"       — in-memory mocks, no hardware needed (dev/macOS).
    "rpi5"       — real I2C1 (GPIO2/3) + SPI0 CE0/CE1 (see hw_config.py).
    "cm5"        — raises NotImplementedError until the CM5 is configured.

    Real transports lazy-import smbus2/spidev so this call is safe on
    machines without those packages. Failures appear when open() is called.
    """
    platform = (config.hw_platform or "mock").lower()

    if platform == "mock":
        return Transports(
            pui=MockPUITransport(),
            wrap_spi=MockSPITransport(),
            feed_spi=MockSPITransport(),
            is_mock=True,
        )

    hw = get_platform(platform)  # raises for unknown or not-ready platforms

    return Transports(
        pui=I2CPUITransport(
            bus_number=hw.i2c.bus_number,
            address=hw.i2c.pui_address,
        ),
        wrap_spi=SPIMotorTransport(
            bus=hw.wrap_spi.bus,
            device=hw.wrap_spi.device,
            max_speed_hz=hw.wrap_spi.max_speed_hz,
            mode=hw.wrap_spi.mode,
        ),
        feed_spi=SPIMotorTransport(
            bus=hw.feed_spi.bus,
            device=hw.feed_spi.device,
            max_speed_hz=hw.feed_spi.max_speed_hz,
            mode=hw.feed_spi.mode,
        ),
        is_mock=False,
    )
