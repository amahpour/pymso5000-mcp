# Rigol MSO5xxx oscilloscope Python library (unofficial)

![A Rigol MSO5074 in a physics laboratory](https://raw.githubusercontent.com/tspspi/pymso5000/master/doc/msophoto.png)

A simple Python library and utility to control and query data from
Rigol MSO5xxx oscilloscopes (not supporting all features of the oscilloscope,
work in progress). This library implements the [Oscilloscope](https://github.com/tspspi/pylabdevs/blob/master/src/labdevices/oscilloscope.py) class from
the [pylabdevs](https://github.com/tspspi/pylabdevs) package which
exposes the public interface.

Patches for raw mode sample query by [MasterJubei](https://github.com/MasterJubei)

## Installing

There is a PyPi package that can be installed using

```
pip install pymso5000-tspspi
```

## MCP Server

This repository includes an MCP (Model Context Protocol) server that enables AI agents
to interact with the oscilloscope. The server exposes 28 tools for device discovery,
channel configuration, timebase/trigger control, and waveform acquisition.

### Setup

First, install the dependencies:

```bash
pip install fastmcp pymso5000-tspspi pylabdevs-tspspi
```

The server auto-discovers the oscilloscope on the network. You can optionally
set a static IP via environment variable if preferred:

```bash
export RIGOL_MSO5000_IP=10.0.0.123   # optional, auto-discovers if not set
export RIGOL_MSO5000_PORT=5555        # optional, defaults to 5555
```

Then add the MCP server to your editor/agent:

#### Claude Code

```bash
claude mcp add rigol-mso5000 -- python3 /path/to/mcp_mso5000.py
```

#### Cursor IDE

Add the following to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "rigol-mso5000": {
      "command": "python3",
      "args": ["/path/to/mcp_mso5000.py"],
      "env": {}
    }
  }
}
```

### Available MCP Tools

| Category | Tools |
|---|---|
| Health & Discovery | `ping`, `discover_devices` |
| Connection | `test_connection`, `connect`, `disconnect`, `get_device_info` |
| Channel Config | `set_channel_enable`, `get_channel_enable`, `set_channel_coupling`, `get_channel_coupling`, `set_channel_scale`, `get_channel_scale`, `set_channel_probe_ratio`, `get_channel_probe_ratio` |
| Timebase | `set_timebase_mode`, `get_timebase_mode`, `set_timebase_scale`, `get_timebase_scale` |
| Trigger | `set_trigger_mode`, `get_trigger_mode`, `set_sweep_mode`, `get_sweep_mode`, `force_trigger` |
| Run Control | `set_run_mode`, `get_run_mode` |
| Waveform | `query_waveform` (saves CSV, returns file path), `query_waveform_summary` (inline stats) |
| Status | `get_full_scope_status` (all config in one call) |

Waveform data is saved to CSV files in the `waveform_data/` directory because the
data can be very large (thousands of points). The file path is returned so the agent
can read or copy the file.

### Network Discovery

To find your oscilloscope on the network:

```bash
python3 find_mso5000.py
```

## Simple example to fetch waveforms:

```
from pymso5000.mso5000 import MSO5000

with MSO5000(address = "10.0.0.123") as mso:
   print(f"Identify: {mso.identify()}")

   mso.set_channel_enable(0, True)
   mso.set_channel_enable(1, True)

   data = mso.query_waveform((0, 1))
   print(data)

   import matplotlib.pyplot as plt
   plt.plot(data['x'], data['y0'], label = "Ch1")
   plt.plot(data['x'], data['y1'], label = "Ch2")
   plt.show()
```

Note that ```numpy``` usage is optional for this implementation.
One can enable numpy support using ```useNumpy = True``` in the
constructor.

## Querying additional statistics

This module allows - via the ```pylabdevs``` base class to query
additional statistics:

* ```mean``` Calculates the mean values and standard deviations
   * A single value for each channels mean at ```["means"]["yN_avg"]```
     and a single value for each standard deviation at ```["means"]["yN_std"]```
     where ```N``` is the channel number
* ```fft``` runs Fourier transform on all queried traces
   * The result is stored in ```["fft"]["yN"]``` (complex values) and
     in ```["fft"]["yN_real"]``` for the real valued Fourier transform.
     Again ```N``` is the channel number
* ```ifft``` runs inverse Fourier transform on all queried traces
   * Works as ```fft``` but runs the inverse Fourier transform and stores
     its result in ```ifft``` instead of ```fft```
* ```correlate``` calculates the correlation between all queried
  waveform pairs.
   * The result of the correlations are stored in ```["correlation"]["yNyM"]```
     for the correlation between channels ```M``` and ```N```
* ```autocorrelate``` performs calculation of the autocorrelation of each
  queried channel.
   * The result of the autocorrelation is stored in ```["autocorrelation"]["yN"]```
     for channel ```N```

To request calculation of statistics pass the string for the
desired statistic or a list of statistics to the ```stats```
parameter of ```query_waveform```:

```
with MSO5000(address = "10.0.0.123") as mso:
	data = mso.query_waveform((1,2), stats = [ 'mean', 'fft' ])
```

## Supported methods

More documentation in progress ...

* ```identify()```
* Connection management (when not using ```with``` context management):
   * ```connect()```
   * ```disconnect()```
* ```set_channel_enable(channel, enabled)```
* ```is_channel_enabled(channel)```
* ```set_sweep_mode(mode)```
* ```get_sweep_mode()```
* ```set_trigger_mode(mode)```
* ```get_trigger_mode()```
* ```force_trigger()```
* ```set_timebase_mode(mode)```
* ```get_timebase_mode()```
* ```set_run_mode(mode)```
* ```get_run_mode()```
* ```set_timebase_scale(secondsPerDivision)```
* ```get_timebase_scale()```
* ```set_channel_coupling(channel, couplingMode)```
* ```get_channel_coupling(channel)```
* ```set_channel_probe_ratio(channel, ratio)```
* ```get_channel_probe_ratio(channel)```
* ```set_channel_scale(channel, scale)```
* ```get_channel_scale(channel)```
* ```query_waveform(channel, stats = None)```
* ```off()```

## CLI fetching utility

This package comes with a ```mso5000fetch``` command line utility. This utility
allows one to simply fetch one or more traces and store them either inside an npz
or a matplotlib plot. In addition it can run all of the ```pylabdevs``` statistics
functions (currently no plot, only stored in the npz) and execute manually assisted
differential scans.

Help for this utility is available via ```mso5000fetch --help```
