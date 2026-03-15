"""
Rigol MSO5000 MCP Server

A Model Context Protocol (MCP) server that enables AI agents to interact with Rigol MSO5000
series oscilloscopes via Ethernet connection. Provides tools for device discovery,
channel control, timebase/trigger configuration, and waveform acquisition.

Waveform data is saved to files (CSV) and the file path is returned, since waveform
data can be very large and would not fit in a JSON response.
"""

from fastmcp import FastMCP
import csv
import logging
import os
import time
from typing import Optional, Dict, Any, List

from pymso5000.mso5000 import MSO5000
from labdevices.oscilloscope import (
    OscilloscopeSweepMode,
    OscilloscopeTriggerMode,
    OscilloscopeTimebaseMode,
    OscilloscopeRunMode,
    OscilloscopeCouplingMode,
)
from find_mso5000 import find_mso5000, test_ip

# Initialize the MCP server
mcp = FastMCP(name="RigolMSO5000MCP")

# Global variable to store the current oscilloscope connection
current_scope: Optional[MSO5000] = None

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
DEFAULT_IP = os.environ.get("RIGOL_MSO5000_IP")
DEFAULT_PORT = int(os.environ.get("RIGOL_MSO5000_PORT", "5555"))

# Output directory for waveform data files
OUTPUT_DIR = os.environ.get(
    "MSO5000_OUTPUT_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "waveform_data"),
)

# Enum string mappings
SWEEP_MODES = {
    "auto": OscilloscopeSweepMode.AUTO,
    "normal": OscilloscopeSweepMode.NORMAL,
    "single": OscilloscopeSweepMode.SINGLE,
}

TRIGGER_MODES = {
    "edge": OscilloscopeTriggerMode.EDGE,
    "pulse": OscilloscopeTriggerMode.PULSE,
    "slope": OscilloscopeTriggerMode.SLOPE,
}

TIMEBASE_MODES = {
    "main": OscilloscopeTimebaseMode.MAIN,
    "xy": OscilloscopeTimebaseMode.XY,
    "roll": OscilloscopeTimebaseMode.ROLL,
}

RUN_MODES = {
    "run": OscilloscopeRunMode.RUN,
    "stop": OscilloscopeRunMode.STOP,
    "single": OscilloscopeRunMode.SINGLE,
}

COUPLING_MODES = {
    "dc": OscilloscopeCouplingMode.DC,
    "ac": OscilloscopeCouplingMode.AC,
    "gnd": OscilloscopeCouplingMode.GND,
}


def _ensure_output_dir():
    """Ensure the waveform output directory exists."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def _require_connection():
    """Raise if no scope is connected."""
    if not current_scope:
        raise RuntimeError("No oscilloscope connected. Use connect() first.")


def _safe_get_sweep_mode():
    """Get sweep mode by querying SCPI directly.

    The installed pymso5000 has a bug where _get_sweep_mode uses scpiCommand
    instead of scpiQuery. Calling the broken method leaves an unread response
    in the TCP buffer, which corrupts all subsequent queries. So we bypass the
    library entirely and query the device directly.
    """
    try:
        resp = current_scope._scpi.scpiQuery(":TRIG:SWE?")
        modes = {"AUTO": "auto", "NORM": "normal", "SING": "single"}
        return modes.get(resp, f"unknown ({resp})")
    except Exception:
        return "unknown"


# ──────────────────────────────────────────────
# Health & Discovery
# ──────────────────────────────────────────────


@mcp.tool()
def ping() -> str:
    """
    Simple health check to verify the MCP server is running.

    Returns:
        str: Always returns "pong" to confirm server is responsive.
    """
    return "pong"


@mcp.tool()
def discover_devices() -> List[Dict[str, Any]]:
    """
    Discover Rigol MSO5000 oscilloscopes on the local network.

    Scans the network for devices listening on port 5555 that respond
    to *IDN? with a RIGOL MSO5xxx identifier.

    Returns:
        List[Dict[str, Any]]: List of discovered devices with IP and device ID.
    """
    try:
        result = find_mso5000()
        if result is None:
            return [{"error": "No MSO5000 devices found on the network"}]

        ip, device_id = result
        return [{"ip": ip, "device_id": device_id}]
    except Exception as e:
        logger.error(f"Device discovery failed: {e}")
        return [{"error": str(e)}]


# ──────────────────────────────────────────────
# Connection Management
# ──────────────────────────────────────────────


@mcp.tool()
def test_connection(ip_address: str = None) -> Dict[str, Any]:
    """
    Test connection to an MSO5000 without establishing a persistent connection.

    Args:
        ip_address: IP address to test. Uses configured/auto-discovered IP if not provided.

    Returns:
        Dict with status, ip, and device_id if successful.
    """
    try:
        if ip_address is None:
            ip_address = DEFAULT_IP
        if ip_address is None:
            result = find_mso5000()
            if result is None:
                return {
                    "status": "failed",
                    "error": "No IP configured and auto-discovery failed. Set RIGOL_MSO5000_IP.",
                }
            ip_address = result[0]

        device_id = test_ip(ip_address, DEFAULT_PORT)
        if device_id:
            return {"status": "success", "ip": ip_address, "device_id": device_id}
        else:
            return {
                "status": "failed",
                "ip": ip_address,
                "error": "No MSO5000 found at this IP",
            }
    except Exception as e:
        return {"status": "failed", "ip": ip_address or "unknown", "error": str(e)}


@mcp.tool()
def connect(ip_address: str = None, port: int = None) -> Dict[str, Any]:
    """
    Connect to a Rigol MSO5000 oscilloscope.

    Establishes a persistent connection. If no IP is provided and none is configured,
    attempts auto-discovery.

    Args:
        ip_address: IP address of the oscilloscope.
        port: Port number (default 5555).

    Returns:
        Dict with connection status and device info.
    """
    global current_scope

    try:
        # Close existing connection
        if current_scope:
            try:
                current_scope.disconnect()
            except Exception:
                pass
            current_scope = None

        # Determine IP
        if ip_address is None:
            ip_address = DEFAULT_IP
        if ip_address is None:
            result = find_mso5000()
            if result is None:
                return {
                    "status": "failed",
                    "error": "No IP configured and auto-discovery failed. Set RIGOL_MSO5000_IP.",
                }
            ip_address = result[0]

        if port is None:
            port = DEFAULT_PORT

        # Create and connect
        current_scope = MSO5000(address=ip_address, port=port)
        current_scope.connect()

        device_info = current_scope.identify()

        return {
            "status": "connected",
            "ip": ip_address,
            "port": port,
            "device_info": device_info,
        }
    except Exception as e:
        current_scope = None
        logger.error(f"Connection failed: {e}")
        return {"status": "failed", "error": str(e)}


@mcp.tool()
def disconnect() -> str:
    """
    Disconnect from the currently connected oscilloscope.

    Returns:
        str: Disconnection status message.
    """
    global current_scope

    if current_scope:
        try:
            current_scope.disconnect()
            current_scope = None
            return "Disconnected successfully"
        except Exception as e:
            current_scope = None
            return f"Error during disconnect: {e}"
    else:
        return "No active connection to disconnect"


@mcp.tool()
def get_device_info() -> Dict[str, Any]:
    """
    Get identification info for the connected oscilloscope.

    Returns:
        Dict with manufacturer, product, serial, and version.
    """
    _require_connection()
    return current_scope.identify()


# ──────────────────────────────────────────────
# Channel Configuration
# ──────────────────────────────────────────────


@mcp.tool()
def set_channel_enable(channel: int, enabled: bool) -> Dict[str, Any]:
    """
    Enable or disable a channel display.

    Args:
        channel: Channel number (1-4). Converted internally to 0-indexed.
        enabled: True to enable, False to disable.

    Returns:
        Dict with status and channel info.
    """
    _require_connection()
    try:
        current_scope.set_channel_enable(channel - 1, enabled)
        return {"status": "success", "channel": channel, "enabled": enabled}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
def get_channel_enable(channel: int) -> Dict[str, Any]:
    """
    Query whether a channel is enabled.

    Args:
        channel: Channel number (1-4).

    Returns:
        Dict with channel enabled state.
    """
    _require_connection()
    try:
        enabled = current_scope.is_channel_enabled(channel - 1)
        return {"status": "success", "channel": channel, "enabled": enabled}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
def set_channel_coupling(channel: int, mode: str) -> Dict[str, Any]:
    """
    Set channel coupling mode.

    Args:
        channel: Channel number (1-4).
        mode: Coupling mode - one of "dc", "ac", "gnd".

    Returns:
        Dict with status and coupling mode.
    """
    _require_connection()
    mode_lower = mode.lower()
    if mode_lower not in COUPLING_MODES:
        return {
            "status": "error",
            "error": f"Invalid coupling mode '{mode}'. Must be one of: dc, ac, gnd",
        }
    try:
        # Bypass library base class validation (missing supportedCouplingModes)
        # and send SCPI command directly.
        ch_idx = channel - 1
        if ch_idx < 0 or ch_idx > 3:
            return {"status": "error", "error": f"Channel {channel} out of range (1-4)"}
        current_scope._scpi.scpiCommand(f":CHAN{channel}:COUP {mode_lower.upper()}")
        return {"status": "success", "channel": channel, "coupling": mode_lower}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
def get_channel_coupling(channel: int) -> Dict[str, Any]:
    """
    Get the coupling mode for a channel.

    Args:
        channel: Channel number (1-4).

    Returns:
        Dict with channel coupling mode (dc, ac, or gnd).
    """
    _require_connection()
    try:
        mode = current_scope.get_channel_coupling(channel - 1)
        return {"status": "success", "channel": channel, "coupling": mode.name.lower()}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
def set_channel_scale(channel: int, scale: float) -> Dict[str, Any]:
    """
    Set the voltage scale for a channel (V/div).

    Args:
        channel: Channel number (1-4).
        scale: Voltage scale in V/div. Valid values depend on probe ratio.
               Base range: 500uV to 10V per div in 1-2-5 steps.

    Returns:
        Dict with status and scale setting.
    """
    _require_connection()
    try:
        current_scope.set_channel_scale(channel - 1, scale)
        return {
            "status": "success",
            "channel": channel,
            "scale_v_per_div": scale,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
def get_channel_scale(channel: int) -> Dict[str, Any]:
    """
    Get the voltage scale for a channel (V/div).

    Args:
        channel: Channel number (1-4).

    Returns:
        Dict with voltage scale in V/div.
    """
    _require_connection()
    try:
        scale = current_scope.get_channel_scale(channel - 1)
        return {
            "status": "success",
            "channel": channel,
            "scale_v_per_div": scale,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
def set_channel_probe_ratio(channel: int, ratio: float) -> Dict[str, Any]:
    """
    Set the probe attenuation ratio for a channel.

    Args:
        channel: Channel number (1-4).
        ratio: Probe ratio. Supported values: 0.0001, 0.0002, 0.0005, 0.001,
               0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10,
               20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000.

    Returns:
        Dict with status and probe ratio.
    """
    _require_connection()
    try:
        current_scope.set_channel_probe_ratio(channel - 1, ratio)
        return {"status": "success", "channel": channel, "probe_ratio": ratio}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
def get_channel_probe_ratio(channel: int) -> Dict[str, Any]:
    """
    Get the probe attenuation ratio for a channel.

    Args:
        channel: Channel number (1-4).

    Returns:
        Dict with probe ratio.
    """
    _require_connection()
    try:
        ratio = current_scope.get_channel_probe_ratio(channel - 1)
        return {"status": "success", "channel": channel, "probe_ratio": ratio}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ──────────────────────────────────────────────
# Timebase Configuration
# ──────────────────────────────────────────────


@mcp.tool()
def set_timebase_mode(mode: str) -> Dict[str, Any]:
    """
    Set the timebase mode.

    Args:
        mode: One of "main", "xy", "roll".

    Returns:
        Dict with status and timebase mode.
    """
    _require_connection()
    mode_lower = mode.lower()
    if mode_lower not in TIMEBASE_MODES:
        return {
            "status": "error",
            "error": f"Invalid timebase mode '{mode}'. Must be one of: main, xy, roll",
        }
    try:
        current_scope.set_timebase_mode(TIMEBASE_MODES[mode_lower])
        return {"status": "success", "timebase_mode": mode_lower}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
def get_timebase_mode() -> Dict[str, Any]:
    """
    Get the current timebase mode.

    Returns:
        Dict with timebase mode (main, xy, or roll).
    """
    _require_connection()
    try:
        mode = current_scope.get_timebase_mode()
        return {"status": "success", "timebase_mode": mode.name.lower()}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
def set_timebase_scale(seconds_per_div: float) -> Dict[str, Any]:
    """
    Set the timebase scale (seconds per division).

    Args:
        seconds_per_div: Time scale in seconds/div. Range depends on model and mode.
                         Typical Y-T range: 5ns/div to 1000s/div.
                         Roll mode: 200ms/div to 1000s/div.

    Returns:
        Dict with status and timebase scale.
    """
    _require_connection()
    try:
        current_scope.set_timebase_scale(seconds_per_div)
        return {"status": "success", "seconds_per_div": seconds_per_div}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
def get_timebase_scale() -> Dict[str, Any]:
    """
    Get the current timebase scale (seconds per division).

    Returns:
        Dict with timebase scale in seconds/div.
    """
    _require_connection()
    try:
        scale = current_scope.get_timebase_scale()
        return {"status": "success", "seconds_per_div": scale}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ──────────────────────────────────────────────
# Trigger Configuration
# ──────────────────────────────────────────────


@mcp.tool()
def set_trigger_mode(mode: str) -> Dict[str, Any]:
    """
    Set the trigger mode.

    Args:
        mode: One of "edge", "pulse", "slope".

    Returns:
        Dict with status and trigger mode.
    """
    _require_connection()
    mode_lower = mode.lower()
    if mode_lower not in TRIGGER_MODES:
        return {
            "status": "error",
            "error": f"Invalid trigger mode '{mode}'. Must be one of: edge, pulse, slope",
        }
    try:
        current_scope.set_trigger_mode(TRIGGER_MODES[mode_lower])
        return {"status": "success", "trigger_mode": mode_lower}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
def get_trigger_mode() -> Dict[str, Any]:
    """
    Get the current trigger mode.

    Returns:
        Dict with trigger mode (edge, pulse, or slope).
    """
    _require_connection()
    try:
        mode = current_scope.get_trigger_mode()
        return {"status": "success", "trigger_mode": mode.name.lower()}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
def set_sweep_mode(mode: str) -> Dict[str, Any]:
    """
    Set the trigger sweep mode.

    Args:
        mode: One of "auto", "normal", "single".

    Returns:
        Dict with status and sweep mode.
    """
    _require_connection()
    mode_lower = mode.lower()
    if mode_lower not in SWEEP_MODES:
        return {
            "status": "error",
            "error": f"Invalid sweep mode '{mode}'. Must be one of: auto, normal, single",
        }
    try:
        current_scope.set_sweep_mode(SWEEP_MODES[mode_lower])
        return {"status": "success", "sweep_mode": mode_lower}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
def get_sweep_mode() -> Dict[str, Any]:
    """
    Get the current trigger sweep mode.

    Returns:
        Dict with sweep mode (auto, normal, or single).
    """
    _require_connection()
    try:
        return {"status": "success", "sweep_mode": _safe_get_sweep_mode()}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
def force_trigger() -> Dict[str, Any]:
    """
    Force an immediate trigger event.

    Returns:
        Dict with status.
    """
    _require_connection()
    try:
        current_scope.force_trigger()
        return {"status": "success", "message": "Trigger forced"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ──────────────────────────────────────────────
# Run Control
# ──────────────────────────────────────────────


@mcp.tool()
def set_run_mode(mode: str) -> Dict[str, Any]:
    """
    Set the oscilloscope run mode.

    Args:
        mode: One of "run", "stop", "single".

    Returns:
        Dict with status and run mode.
    """
    _require_connection()
    mode_lower = mode.lower()
    if mode_lower not in RUN_MODES:
        return {
            "status": "error",
            "error": f"Invalid run mode '{mode}'. Must be one of: run, stop, single",
        }
    try:
        current_scope.set_run_mode(RUN_MODES[mode_lower])
        return {"status": "success", "run_mode": mode_lower}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
def get_run_mode() -> Dict[str, Any]:
    """
    Get the current run mode.

    Returns:
        Dict with run mode (run, stop, or single).
    """
    _require_connection()
    try:
        mode = current_scope.get_run_mode()
        mode_name = mode.name.lower() if mode else "unknown"
        return {"status": "success", "run_mode": mode_name}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ──────────────────────────────────────────────
# Waveform Acquisition
# ──────────────────────────────────────────────


@mcp.tool()
def query_waveform(channels: str, filename: str = None) -> Dict[str, Any]:
    """
    Acquire waveform data from one or more channels and save to a CSV file.

    The waveform data is saved to a CSV file because it can be very large (thousands
    of data points). The file path is returned so the agent can read it.

    Args:
        channels: Comma-separated channel numbers, e.g. "1" or "1,2,3".
                  Channels are numbered 1-4.
        filename: Optional output filename (without extension). If not provided,
                  a timestamped name is generated automatically.

    Returns:
        Dict with status, file_path to the CSV, number of points, and channel list.
        The CSV file has columns: time_s, ch1_v, ch2_v, etc.
    """
    _require_connection()
    try:
        # Parse channel list
        ch_list = [int(c.strip()) for c in channels.split(",")]
        for ch in ch_list:
            if ch < 1 or ch > 4:
                return {
                    "status": "error",
                    "error": f"Channel {ch} out of range. Must be 1-4.",
                }

        # Convert to 0-indexed for the library
        ch_indices = [ch - 1 for ch in ch_list]

        # Query waveform
        if len(ch_indices) == 1:
            data = current_scope.query_waveform(ch_indices[0])
            # Normalize single-channel response to multi-channel format
            data[f"y{ch_indices[0]}"] = data.pop("y")
        else:
            data = current_scope.query_waveform(ch_indices)

        # Generate filename
        if filename is None:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            ch_str = "_".join(str(c) for c in ch_list)
            filename = f"waveform_ch{ch_str}_{timestamp}"

        _ensure_output_dir()
        filepath = os.path.join(OUTPUT_DIR, f"{filename}.csv")

        # Write CSV
        num_points = len(data["x"])
        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            # Header
            header = ["time_s"] + [f"ch{ch}_v" for ch in ch_list]
            writer.writerow(header)
            # Data rows
            for i in range(num_points):
                row = [data["x"][i]]
                for ch_idx in ch_indices:
                    row.append(data[f"y{ch_idx}"][i])
                writer.writerow(row)

        return {
            "status": "success",
            "file_path": filepath,
            "num_points": num_points,
            "channels": ch_list,
            "time_range_s": {
                "start": data["x"][0],
                "end": data["x"][-1],
            },
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
def query_waveform_summary(channels: str) -> Dict[str, Any]:
    """
    Acquire waveform data and return a statistical summary (no file saved).

    Useful for quick measurements without needing the full waveform file.

    Args:
        channels: Comma-separated channel numbers, e.g. "1" or "1,2".
                  Channels are numbered 1-4.

    Returns:
        Dict with per-channel statistics: min, max, mean, peak-to-peak voltage,
        number of points, and time range.
    """
    _require_connection()
    try:
        ch_list = [int(c.strip()) for c in channels.split(",")]
        for ch in ch_list:
            if ch < 1 or ch > 4:
                return {
                    "status": "error",
                    "error": f"Channel {ch} out of range. Must be 1-4.",
                }

        ch_indices = [ch - 1 for ch in ch_list]

        if len(ch_indices) == 1:
            data = current_scope.query_waveform(ch_indices[0])
            data[f"y{ch_indices[0]}"] = data.pop("y")
        else:
            data = current_scope.query_waveform(ch_indices)

        num_points = len(data["x"])
        summary = {
            "status": "success",
            "num_points": num_points,
            "time_range_s": {
                "start": data["x"][0],
                "end": data["x"][-1],
            },
            "channels": {},
        }

        for ch, ch_idx in zip(ch_list, ch_indices):
            y = data[f"y{ch_idx}"]
            v_min = min(y)
            v_max = max(y)
            v_mean = sum(y) / len(y)
            summary["channels"][f"ch{ch}"] = {
                "min_v": v_min,
                "max_v": v_max,
                "mean_v": v_mean,
                "vpp": v_max - v_min,
            }

        return summary
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
def get_full_scope_status() -> Dict[str, Any]:
    """
    Get a comprehensive status snapshot of the oscilloscope.

    Returns all channel enable/coupling/scale/probe states, timebase, trigger,
    sweep, and run mode in a single call. Useful for understanding the current
    scope configuration at a glance.

    Returns:
        Dict with complete oscilloscope configuration.
    """
    _require_connection()
    try:
        status = {
            "status": "success",
            "device_info": current_scope.identify(),
            "timebase": {
                "mode": current_scope.get_timebase_mode().name.lower(),
                "scale_s_per_div": current_scope.get_timebase_scale(),
            },
            "trigger": {
                "mode": current_scope.get_trigger_mode().name.lower(),
            },
            "sweep_mode": _safe_get_sweep_mode(),
            "run_mode": current_scope.get_run_mode().name.lower()
            if current_scope.get_run_mode()
            else "unknown",
            "channels": {},
        }

        for ch in range(4):
            ch_num = ch + 1
            enabled = current_scope.is_channel_enabled(ch)
            ch_info = {"enabled": enabled}
            if enabled:
                ch_info["coupling"] = current_scope.get_channel_coupling(ch).name.lower()
                ch_info["scale_v_per_div"] = current_scope.get_channel_scale(ch)
                ch_info["probe_ratio"] = current_scope.get_channel_probe_ratio(ch)
            status["channels"][f"ch{ch_num}"] = ch_info

        return status
    except Exception as e:
        return {"status": "error", "error": str(e)}


def main():
    """Entry point for the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
