# ROS 2 Package [bob_synth](https://github.com/bob-ros2/bob_synth)

[![CI](https://github.com/bob-ros2/bob_synth/actions/workflows/ros2_ci.yaml/badge.svg)](https://github.com/bob-ros2/bob_synth/actions/workflows/ros2_ci.yaml)
[![amd64](https://img.shields.io/github/actions/workflow/status/bob-ros2/bob_synth/docker.yml?label=amd64&logo=docker)](https://github.com/bob-ros2/bob_synth/actions/workflows/docker.yml)
[![arm64](https://img.shields.io/github/actions/workflow/status/bob-ros2/bob_synth/docker.yml?label=arm64&logo=docker)](https://github.com/bob-ros2/bob_synth/actions/workflows/docker.yml)

**Ultra-lightweight, resource-efficient Multi-Threaded Synthesizer for ROS 2.**

`bob_synth` is a flexible audio generation node capable of producing real-time waveforms (sine, square, triangle, sawtooth) with a full ADSR envelope. It supports multi-threaded execution for glitch-free audio and can output data to both ROS topics and Unix FIFO pipes.

## Key Features
- **Multi-Threaded Execution**: Uses `MultiThreadedExecutor` and `ReentrantCallbackGroups` to ensure timing-critical audio generation isn't blocked by parameter updates or JSON parsing.
- **Dynamic Waveform Generation**: Supports `sine`, `square`, `triangle`, and `sawtooth` (aka `saw`).
- **Full ADSR Envelope**: High-resolution Attack, Decay, Sustain, and Release controls.
- **JSON Configuration Topic**: Change all synthesis parameters on-the-fly via a single JSON string topic.
- **FIFO Pipe Output**: Optional raw 16-bit PCM (Stereo) output to a Unix FIFO for external processing.
- **Environment Variable Overrides**: All parameters can be set via `SYNTH_*` environment variables.

## Installation & Building

```bash
cd ~/ros2_ws/src
git clone https://github.com/bob-ros2/bob_synth.git
cd ..
colcon build --packages-select bob_synth
source install/setup.bash
```

## Usage

Run the node with default settings:
```bash
ros2 run bob_synth synth_node
```

### Remapping to the Eva Streamer
```bash
ros2 run bob_synth synth_node --ros-args --remap audio_out:=/eva/streamer/in1
```

## ROS 2 API

### Parameters (with Env Var support)
All parameters can be overridden using the `SYNTH_` prefix in uppercase (e.g. `export SYNTH_FREQUENCY=220.0`).

| Parameter | Default | Env Var | Description |
|-----------|---------|---------|-------------|
| `frequency` | `440.0` | `SYNTH_FREQUENCY` | Base oscillator frequency (Hz). |
| `waveform` | `sine` | `SYNTH_WAVEFORM` | Waveform (`sine`, `square`, `triangle`, `saw`). |
| `amplitude` | `0.5` | `SYNTH_AMPLITUDE` | Master volume (0.0 to 1.0). |
| `note_on` | `false` | `SYNTH_NOTE_ON` | Triggers the ADSR envelope. |
| `attack` | `0.1` | `SYNTH_ATTACK` | Attack time in seconds. |
| `decay` | `0.1` | `SYNTH_DECAY` | Decay time in seconds. |
| `sustain` | `0.7` | `SYNTH_SUSTAIN` | Sustain level (0.0 to 1.0).|
| `release` | `0.2` | `SYNTH_RELEASE` | Release time in seconds. |
| `pipe_path` | `/tmp/synth_pipe` | `SYNTH_PIPE_PATH` | Destination for raw PCM pipe. |
| `use_pipe` | `false` | `SYNTH_USE_PIPE` | Enable/Disable FIFO output. |

### Topics
| Topic | Type | Mode | Description |
|-------|------|------|-------------|
| `audio_out` | `std_msgs/Int16MultiArray` | Pub | Raw 16-bit PCM audio chunks. |
| `config_in` | `std_msgs/String` | Sub | JSON string for dynamic parameter updates. |

## Examples

### 1. Trigger a Note via JSON (Note ON)
```bash
ros2 topic pub --once /config_in std_msgs/msg/String "data: '{\"note_on\": true, \"frequency\": 220.0, \"waveform\": \"saw\"}'"
```

### 2. Change ADSR and Waveform
```bash
ros2 topic pub --once /config_in std_msgs/msg/String "data: '{\"attack\": 0.5, \"release\": 1.0, \"waveform\": \"triangle\"}'"
```

### 3. Record raw FIFO output
```bash
# Enable pipe
ros2 param set /bob_synth use_pipe true
# Capture to file (raw PCM s16le, 44100Hz, Stereo)
cat /tmp/synth_pipe > output.raw
```
