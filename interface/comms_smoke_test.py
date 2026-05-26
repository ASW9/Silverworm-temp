#!/usr/bin/env python3
"""
Silverworm comms smoke test — interactive + one-shot modes.

Interactive (default):
    python comms_smoke_test.py              # auto-detect hardware; fall back to mock
    python comms_smoke_test.py --mock       # force loopback mock (no hardware needed)

One-shot automated tests (CI / bench scripts):
    python comms_smoke_test.py --i2c --timeout 10
    python comms_smoke_test.py --spi --speed 25 --tolerance 0
    python comms_smoke_test.py --i2c --spi --speed 25

On the Raspberry Pi (real hardware):
    pip install smbus2 spidev
    python comms_smoke_test.py --i2c-bus 1 --i2c-address 0x42
    python comms_smoke_test.py --spi-bus 0 --spi-device 0 --speed 25
"""

from __future__ import annotations

import argparse
import struct
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from comms.motor_spi import (
    CommandPrefix,
    CurrentSpeed,
    ErrorResponse,
    MockSPITransport,
    SPIMotorTransport,
    StopType,
    build_set_speed,
    build_start,
    build_stop,
    build_test_movement,
    parse_arduino_response,
)
from comms.pui import (
    I2CPUITransport,
    PUITransport,
    parse_pui_message,
)


# ── output helpers ────────────────────────────────────────────────────────────

_print_lock = threading.Lock()


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _hex(data: bytes) -> str:
    return " ".join(f"{b:02x}" for b in data)


def _log(arrow: str, channel: str, msg: str) -> None:
    with _print_lock:
        print(f"  {_ts()}  {arrow}  [{channel:3}]  {msg}", flush=True)


def out(channel: str, msg: str) -> None:
    _log("-->", channel, msg)


def _in(channel: str, msg: str) -> None:
    _log("<--", channel, msg)


def info(msg: str) -> None:
    with _print_lock:
        print(f"  {_ts()}       ---   {msg}", flush=True)


def ok(msg: str) -> None:
    with _print_lock:
        print(f"  {_ts()}      PASS  {msg}", flush=True)


def fail(msg: str) -> None:
    with _print_lock:
        print(f"  {_ts()}      FAIL  {msg}", flush=True)


# ── loopback transports (no hardware) ────────────────────────────────────────

class LoopbackSPITransport(MockSPITransport):
    """
    Extends MockSPITransport to auto-reply with CURRENT_SPEED when it receives
    a START or SET_SPEED packet. Lets you see the full roundtrip without any
    hardware attached.
    """

    def send(self, data: bytes) -> None:
        super().send(data)
        reply = self._auto_reply(data)
        if reply:
            self.inject_response(reply)

    @staticmethod
    def _auto_reply(data: bytes) -> Optional[bytes]:
        if not data:
            return None
        prefix = data[0]
        payload = data[1:]
        if prefix in (CommandPrefix.START, CommandPrefix.SET_SPEED) and len(payload) >= 2:
            speed = struct.unpack("<H", payload[:2])[0]
            return bytes([0x01]) + struct.pack("<H", speed)  # CURRENT_SPEED echo
        if prefix == CommandPrefix.STOP:
            return bytes([0x03, 0x00])  # SequenceStatus(0)
        return None


class LoopbackI2CTransport(PUITransport):
    """
    Replays a canned sequence of PUI messages so the I2C monitor shows
    live output without a real ESP32.
    """

    _MESSAGES = ["D1+1", "D1-2", "D2+1", "AS1", "AS0", "TP"]

    def __init__(self, interval: float = 1.5):
        self._idx = 0
        self._last = 0.0
        self._interval = interval

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def read_messages(self) -> List[str]:
        now = time.monotonic()
        if now - self._last < self._interval:
            return []
        self._last = now
        msg = self._MESSAGES[self._idx % len(self._MESSAGES)]
        self._idx += 1
        return [msg]


# ── I2C background monitor ────────────────────────────────────────────────────

class I2CMonitor(threading.Thread):
    """Continuously polls the I2C transport and logs every incoming message."""

    def __init__(self, transport: PUITransport, poll_interval: float = 0.05):
        super().__init__(daemon=True, name="I2CMonitor")
        self._transport = transport
        self._poll = poll_interval
        self._stop_event = threading.Event()

    def run(self) -> None:
        try:
            self._transport.open()
            while not self._stop_event.is_set():
                for raw in self._transport.read_messages():
                    parsed = parse_pui_message(raw)
                    _in("I2C", f"raw={raw!r:<14}  parsed={parsed}")
                time.sleep(self._poll)
        except Exception as exc:
            info(f"I2C monitor error: {exc}")
        finally:
            self._transport.close()

    def stop(self) -> None:
        self._stop_event.set()
        self.join(timeout=1.0)


# ── SPI send helper ───────────────────────────────────────────────────────────

def spi_roundtrip(transport, data: bytes, label: str) -> List:
    """Send a packet, drain the inbox, log everything, return parsed responses."""
    out("SPI", f"{label:<30}  bytes: {_hex(data)}")
    transport.send(data)
    time.sleep(0.05)
    responses = []
    for packet in transport.read():
        parsed = parse_arduino_response(packet)
        _in("SPI", f"bytes: {_hex(packet):<12}  parsed={parsed}")
        responses.append(parsed)
    if not responses:
        info("SPI  (no response received)")
    return responses


# ── one-shot automated tests ──────────────────────────────────────────────────

def one_shot_i2c(args: argparse.Namespace, transport: PUITransport) -> bool:
    info(
        f"I2C one-shot: bus={args.i2c_bus} addr=0x{args.i2c_address:02x} "
        f"— listening for {args.timeout:.1f}s"
    )
    info("Move a dial, flip the mode switch, or press power on the ESP32 panel.")
    saw = False
    try:
        transport.open()
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            for raw in transport.read_messages():
                parsed = parse_pui_message(raw)
                _in("I2C", f"raw={raw!r:<14}  parsed={parsed}")
                if parsed is not None:
                    saw = True
            time.sleep(args.poll_interval)
    finally:
        transport.close()

    if saw:
        ok("I2C received at least one valid PUI message")
    else:
        fail("I2C: no valid message received in timeout window")
    return saw


def one_shot_spi(args: argparse.Namespace, transport) -> bool:
    expected = args.speed
    info(
        f"SPI one-shot: /dev/spidev{args.spi_bus}.{args.spi_device} "
        f"@ {args.spi_hz} Hz — sending SET_SPEED {expected}"
    )
    try:
        transport.open()
        data = build_set_speed(expected)
        out("SPI", f"SET_SPEED speed={expected:<5}  bytes: {_hex(data)}")
        transport.send(data)

        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            for packet in transport.read():
                parsed = parse_arduino_response(packet)
                _in("SPI", f"bytes: {_hex(packet):<12}  parsed={parsed}")
                if isinstance(parsed, CurrentSpeed):
                    delta = abs(parsed.speed - expected)
                    if delta <= args.tolerance:
                        ok(f"SPI CURRENT_SPEED={parsed.speed} (expected={expected}, delta={delta})")
                        return True
                    fail(
                        f"SPI CURRENT_SPEED={parsed.speed} outside tolerance "
                        f"(expected={expected} ±{args.tolerance})"
                    )
                    return False
                if isinstance(parsed, ErrorResponse):
                    fail(f"SPI error_code={parsed.error_code}")
                    return False
            time.sleep(args.poll_interval)
    finally:
        transport.close()

    fail("SPI: no CURRENT_SPEED response in timeout window")
    return False


# ── interactive mode ──────────────────────────────────────────────────────────

_MENU = """\

Commands
  1 [speed]    START motor           (default 25)      e.g.  1 100
  2            STOP  (ramp-down)
  3 [speed]    SET_SPEED             (default 25)      e.g.  3 50
  4 [type]     TEST_MOVEMENT type                      e.g.  4 1
  i            Toggle I2C background monitor on/off
  h            Show this menu
  q            Quit
"""


def interactive(args: argparse.Namespace, spi_transport, i2c_transport) -> None:
    info("Interactive mode — type a command and press Enter.")
    print(_MENU)

    monitor: Optional[I2CMonitor] = None

    def start_monitor() -> None:
        nonlocal monitor
        if monitor and monitor.is_alive():
            info("I2C monitor already running")
            return
        monitor = I2CMonitor(i2c_transport, poll_interval=args.poll_interval)
        monitor.start()
        info("I2C monitor started — incoming PUI messages will appear as <-- lines")

    def stop_monitor() -> None:
        nonlocal monitor
        if monitor:
            monitor.stop()
            monitor = None
            info("I2C monitor stopped")

    try:
        spi_transport.open()
        info("SPI transport open")
        start_monitor()

        while True:
            try:
                with _print_lock:
                    sys.stdout.write("\n> ")
                    sys.stdout.flush()
                line = sys.stdin.readline()
                if not line:   # EOF
                    break
                line = line.strip()
            except KeyboardInterrupt:
                print()
                break

            if not line:
                continue

            parts = line.split()
            cmd = parts[0].lower()

            if cmd in ("q", "quit", "exit"):
                break
            elif cmd in ("h", "help", "?"):
                print(_MENU)
            elif cmd == "1":
                speed = int(parts[1]) if len(parts) > 1 else 25
                spi_roundtrip(spi_transport, build_start(speed), f"START speed={speed}")
            elif cmd == "2":
                spi_roundtrip(spi_transport, build_stop(StopType.RAMP_DOWN), "STOP (ramp-down)")
            elif cmd == "3":
                speed = int(parts[1]) if len(parts) > 1 else 25
                spi_roundtrip(spi_transport, build_set_speed(speed), f"SET_SPEED speed={speed}")
            elif cmd == "4":
                mt = int(parts[1]) if len(parts) > 1 else 1
                spi_roundtrip(spi_transport, build_test_movement(mt), f"TEST_MOVEMENT type={mt}")
            elif cmd == "i":
                if monitor and monitor.is_alive():
                    stop_monitor()
                else:
                    start_monitor()
            else:
                with _print_lock:
                    print(f"  Unknown command: {line!r}")
                print(_MENU)

    finally:
        stop_monitor()
        spi_transport.close()
        info("Closed. Bye.")


# ── transport factory ─────────────────────────────────────────────────────────

def _make_transports(args: argparse.Namespace):
    if args.mock:
        info("Mock mode: loopback transports (no hardware)")
        return LoopbackSPITransport(), LoopbackI2CTransport()

    try:
        import spidev  # type: ignore[import]
        import smbus2  # type: ignore[import]
        spi = SPIMotorTransport(
            bus=args.spi_bus,
            device=args.spi_device,
            max_speed_hz=args.spi_hz,
            read_length=args.spi_read_length,
        )
        i2c = I2CPUITransport(
            bus_number=args.i2c_bus,
            address=args.i2c_address,
            read_length=args.i2c_read_length,
        )
        info("Hardware libraries found (spidev + smbus2) — using real transports")
        return spi, i2c
    except ImportError as exc:
        info(f"Hardware libs not available ({exc}) — falling back to loopback mock")
        return LoopbackSPITransport(), LoopbackI2CTransport()


# ── argument parsing ──────────────────────────────────────────────────────────

def parse_args(argv: list) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--mock", action="store_true",
        help="force loopback mock transports (no hardware required)",
    )
    parser.add_argument("--i2c", action="store_true", help="one-shot I2C test then exit")
    parser.add_argument("--spi", action="store_true", help="one-shot SPI test then exit")
    parser.add_argument("--timeout", type=float, default=10.0, metavar="S",
                        help="one-shot test timeout in seconds (default 10)")
    parser.add_argument("--poll-interval", type=float, default=0.05, metavar="S",
                        help="poll interval in seconds (default 0.05)")
    parser.add_argument("--speed", type=int, default=25,
                        help="speed value for SPI tests (uint16)")
    parser.add_argument("--tolerance", type=int, default=0,
                        help="allowed speed-unit error for one-shot SPI test")

    g_i2c = parser.add_argument_group("I2C options")
    g_i2c.add_argument("--i2c-bus", type=int, default=1)
    g_i2c.add_argument("--i2c-address", type=lambda v: int(v, 0), default=0x42,
                       metavar="ADDR", help="hex OK: 0x42")
    g_i2c.add_argument("--i2c-read-length", type=int, default=32)

    g_spi = parser.add_argument_group("SPI options")
    g_spi.add_argument("--spi-bus", type=int, default=0)
    g_spi.add_argument("--spi-device", type=int, default=0)
    g_spi.add_argument("--spi-hz", type=int, default=500_000)
    g_spi.add_argument("--spi-read-length", type=int, default=3)

    return parser.parse_args(argv)


# ── entry point ───────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    print()
    print("  ╔══════════════════════════════════════╗")
    print("  ║   Silverworm Comms Smoke Test        ║")
    print("  ╚══════════════════════════════════════╝")
    print()
    print("  Format:  timestamp  -->/<--  [channel]  message")
    print()

    spi_transport, i2c_transport = _make_transports(args)

    if args.i2c or args.spi:
        results = []
        if args.i2c:
            results.append(one_shot_i2c(args, i2c_transport))
        if args.spi:
            results.append(one_shot_spi(args, spi_transport))
        print()
        return 0 if all(results) else 1

    interactive(args, spi_transport, i2c_transport)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
