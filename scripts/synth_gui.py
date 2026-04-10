#!/usr/bin/env python3
# Copyright 2026 Bob Ros
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""GUI and Audio Player for Bob Synth."""

import signal
import threading
import tkinter as tk
from tkinter import ttk

from rcl_interfaces.msg import Parameter, ParameterType, ParameterValue
from rcl_interfaces.srv import SetParameters
import rclpy
from rclpy.node import Node
import sounddevice as sd
from std_msgs.msg import Int16MultiArray

import numpy as np


class SynthGUI(Node):
    """ROS 2 Node for handling audio playback and parameter control."""

    def __init__(self):
        super().__init__('synth_gui')

        # Audio parameters
        self.sample_rate = 44100
        self.channels = 2
        self.volume = 0.5

        # Audio Buffer (Internal Ring Buffer)
        self.buffer = np.zeros((self.sample_rate, self.channels), dtype='int16')
        self.write_ptr = 0
        self.read_ptr = 0
        self.buffer_lock = threading.Lock()

        # ROS Communication
        self.sub = self.create_subscription(
            Int16MultiArray, 'audio_out', self.audio_callback, 10
        )
        self.param_client = self.create_client(SetParameters, '/bob_synth/set_parameters')

        # Audio Stream
        self.stream = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype='int16',
            callback=self.stream_callback,
            blocksize=512  # Smaller blocks for lower latency
        )
        self.stream.start()
        self.get_logger().info("Audio Player (Buffered) & Control GUI started")

    def audio_callback(self, msg):
        """Handle incoming audio data from ROS topic."""
        data = np.array(msg.data, dtype=np.int16).reshape(-1, self.channels)
        if self.volume != 1.0:
            data = (data.astype(np.float32) * self.volume).astype(np.int16)

        with self.buffer_lock:
            # Write to ring buffer
            n = len(data)
            space = self.buffer.shape[0]
            if self.write_ptr + n <= space:
                self.buffer[self.write_ptr:self.write_ptr + n] = data
            else:
                first = space - self.write_ptr
                self.buffer[self.write_ptr:] = data[:first]
                self.buffer[:n - first] = data[first:]
            self.write_ptr = (self.write_ptr + n) % space

    def stream_callback(self, outdata, frames, time, status):
        """Fill sounddevice output buffer from ring buffer."""
        with self.buffer_lock:
            # Calculate available data
            available = (self.write_ptr - self.read_ptr) % self.buffer.shape[0]

            if available < frames:
                # Underrun, fill with what we have and zero the rest
                if available > 0:
                    n = available
                    if self.read_ptr + n <= self.buffer.shape[0]:
                        outdata[:n] = self.buffer[self.read_ptr:self.read_ptr + n]
                    else:
                        first = self.buffer.shape[0] - self.read_ptr
                        outdata[:first] = self.buffer[self.read_ptr:]
                        outdata[first:n] = self.buffer[:n - first]
                    self.read_ptr = (self.read_ptr + n) % self.buffer.shape[0]
                    outdata[n:] = 0
                else:
                    outdata.fill(0)
            else:
                # Read from ring buffer
                n = frames
                if self.read_ptr + n <= self.buffer.shape[0]:
                    outdata[:] = self.buffer[self.read_ptr:self.read_ptr + n]
                else:
                    first = self.buffer.shape[0] - self.read_ptr
                    outdata[:first] = self.buffer[self.read_ptr:]
                    outdata[first:n] = self.buffer[:n - first]
                self.read_ptr = (self.read_ptr + n) % self.buffer.shape[0]

    def set_param(self, name, value, p_type):
        """Send parameter update request to synth node."""
        if not self.param_client.service_is_ready():
            return
        req = SetParameters.Request()
        p = Parameter()
        p.name = name
        pval = ParameterValue()
        pval.type = p_type
        if p_type == ParameterType.PARAMETER_DOUBLE:
            pval.double_value = float(value)
        elif p_type == ParameterType.PARAMETER_BOOL:
            pval.bool_value = bool(value)
        elif p_type == ParameterType.PARAMETER_STRING:
            pval.string_value = str(value)
        p.value = pval
        req.parameters.append(p)
        self.param_client.call_async(req)


class MainGUI:
    """Tkinter-based GUI for synth control."""

    def __init__(self, ros_node):
        self.node = ros_node
        self.root = tk.Tk()
        self.root.title("Bob Synth - Moog Edition")
        self.root.geometry("750x860")
        self.root.configure(bg="#0f0f0f")

        # Color Palette - Muted Premium Tone
        bg_color = "#0f0f0f"
        panel_color = "#1a1a1a"
        accent_magenta = "#b000b0"
        accent_cyan = "#00a1a1"
        text_color = "#c0c0c0"

        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TFrame", background=bg_color)
        style.configure("TLabel", background=bg_color, foreground=text_color, font=("Verdana", 9))
        style.configure("Header.TLabel", font=("Verdana", 14, "bold"), foreground=accent_magenta)
        style.configure("Slogan.TLabel", font=("Courier", 10, "italic"), foreground="#888")

        style.configure("TLabelframe", background=panel_color, bordercolor="#333", relief="flat")
        style.configure("TLabelframe.Label", background=panel_color, foreground=accent_cyan,
                        font=("Verdana", 10, "bold"))

        # --- Custom Slider Look ---
        style.configure("TScale", background=panel_color, troughcolor="#222",
                        bordercolor="#333", lightcolor=accent_cyan, darkcolor=accent_cyan)

        # --- Header ---
        header_frame = ttk.Frame(self.root, padding=10)
        header_frame.pack(fill="x")
        ttk.Label(header_frame, text="BOB SYNTH for AI's", style="Header.TLabel").pack()
        ttk.Label(header_frame, text="groove into your heart ...",
                  style="Slogan.TLabel").pack()

        # --- Main Layout Sections ---
        top_container = ttk.Frame(self.root)
        top_container.pack(fill="both", expand=True, padx=5, pady=5)

        # 1. LEFT COLUMN: OSCILLATOR & MODULATION
        left_col = ttk.Frame(top_container)
        left_col.pack(side="left", fill="both", expand=True)

        # Oscillator
        o_frame = ttk.LabelFrame(left_col, text=" OSCILLATOR (Core) ", padding=12)
        o_frame.pack(fill="x", padx=10, pady=8)

        ttk.Label(o_frame, text="Waveform Type", background=panel_color).pack()
        self.wave_v = tk.StringVar(value="sine")
        w_menu = ttk.OptionMenu(o_frame, self.wave_v, "sine", "sine", "square", "sawtooth",
                                command=lambda e: self.node.set_param(
                                    "waveform", self.wave_v.get(),
                                    ParameterType.PARAMETER_STRING))
        w_menu.pack(fill="x", pady=5)

        ttk.Label(o_frame, text="Base Frequency (Hz)", background=panel_color).pack()
        self.freq_v = tk.DoubleVar(value=440.0)
        f_scale = ttk.Scale(o_frame, from_=20, to=2000, orient="horizontal",
                            variable=self.freq_v,
                            command=lambda e: self.node.set_param(
                                "frequency", self.freq_v.get(),
                                ParameterType.PARAMETER_DOUBLE))
        f_scale.pack(fill="x", pady=5)

        # Modulation (LFO)
        m_frame = ttk.LabelFrame(left_col, text=" MODULATION (LFO) ", padding=12)
        m_frame.pack(fill="x", padx=10, pady=8)

        ttk.Label(m_frame, text="LFO Frequency (Hz)", background=panel_color).pack()
        self.mod_freq_v = tk.DoubleVar(value=5.0)
        mf_scale = ttk.Scale(m_frame, from_=0, to=20, orient="horizontal",
                             variable=self.mod_freq_v,
                             command=lambda e: self.send_mod("mod_frequency"))
        mf_scale.pack(fill="x", pady=5)

        ttk.Label(m_frame, text="LFO Depth", background=panel_color).pack()
        self.mod_depth_v = tk.DoubleVar(value=0.0)
        md_scale = ttk.Scale(m_frame, from_=0, to=100, orient="horizontal",
                             variable=self.mod_depth_v,
                             command=lambda e: self.send_mod("mod_depth"))
        md_scale.pack(fill="x", pady=5)

        # 2. RIGHT COLUMN: FILTER & ENVELOPE
        right_col = ttk.Frame(top_container)
        right_col.pack(side="right", fill="both", expand=True)

        # Filter
        f_frame = ttk.LabelFrame(right_col, text=" FILTER (Precise SVF) ", padding=12)
        f_frame.pack(fill="x", padx=10, pady=8)

        ttk.Label(f_frame, text="Cutoff Frequency (Hz)", background=panel_color).pack()
        self.cutoff_v = tk.DoubleVar(value=1000.0)
        c_scale = ttk.Scale(f_frame, from_=20, to=12000, orient="horizontal",
                            variable=self.cutoff_v,
                            command=lambda e: self.send_filter("filter_cutoff"))
        c_scale.pack(fill="x", pady=5)

        ttk.Label(f_frame, text="Resonance", background=panel_color).pack()
        self.res_v = tk.DoubleVar(value=0.0)
        r_scale = ttk.Scale(f_frame, from_=0, to=0.95, orient="horizontal",
                            variable=self.res_v,
                            command=lambda e: self.send_filter("filter_resonance"))
        r_scale.pack(fill="x", pady=5)

        # Envelope (ADSR)
        a_frame = ttk.LabelFrame(right_col, text=" ENVELOPE (ADSR) ", padding=12)
        a_frame.pack(fill="both", expand=True, padx=10, pady=8)

        self.adsr = {}
        for p in ["attack", "decay", "sustain", "release"]:
            ttk.Label(a_frame, text=p.capitalize(), background=panel_color).pack()
            self.adsr[p] = tk.DoubleVar(value=0.1 if p != "sustain" else 0.7)
            s = ttk.Scale(a_frame, from_=0, to=1.0, orient="horizontal",
                          variable=self.adsr[p],
                          command=lambda e, name=p: self.send_adsr(name))
            s.pack(fill="x", pady=2)

        # 3. MASTER SECTION (Full Width)
        master_frame = ttk.LabelFrame(self.root, text=" MASTER CONTROLS ", padding=12)
        master_frame.pack(fill="x", padx=15, pady=5)

        ttk.Label(master_frame, text="Master Output Gain", background=panel_color).pack()
        self.amp_v = tk.DoubleVar(value=0.5)
        a_scale = ttk.Scale(master_frame, from_=0, to=1.0, orient="horizontal",
                            variable=self.amp_v,
                            command=lambda e: self.node.set_param(
                                "amplitude", self.amp_v.get(),
                                ParameterType.PARAMETER_DOUBLE))
        a_scale.pack(fill="x", pady=5)

        # 4. TRIGGER BUTTON (Full Width)
        btn_frame = ttk.Frame(self.root, padding=15)
        btn_frame.pack(fill="x")

        self.note_v = tk.BooleanVar(value=False)
        self.note_btn = tk.Button(btn_frame, text="TRIGGER NOTE", font=("Verdana", 12, "bold"),
                                  bg=accent_cyan, fg="#000000", activebackground=accent_magenta,
                                  relief="flat", height=2, command=self.toggle_note)
        self.note_btn.pack(fill="x")

    def send_mod(self, name):
        """Send LFO parameter update to synth node."""
        if name == "mod_frequency":
            val = self.mod_freq_v.get()
        else:
            val = self.mod_depth_v.get()
        self.node.set_param(name, val, ParameterType.PARAMETER_DOUBLE)

    def send_filter(self, name):
        """Send filter parameter update to synth node."""
        val = self.cutoff_v.get() if name == "filter_cutoff" else self.res_v.get()
        self.node.set_param(name, val, ParameterType.PARAMETER_DOUBLE)

    def send_adsr(self, name):
        """Send ADSR parameter update to synth node."""
        val = self.adsr[name].get()
        self.node.set_param(name, val, ParameterType.PARAMETER_DOUBLE)

    def toggle_note(self):
        """Toggle standard note_on parameter."""
        new_state = not self.note_v.get()
        self.note_v.set(new_state)
        self.node.set_param("note_on", new_state, ParameterType.PARAMETER_BOOL)
        accent_magenta = "#b000b0"
        accent_cyan = "#00a1a1"

        if new_state:
            self.note_btn.config(text="RELEASING...", bg=accent_magenta, fg="#000000")
        else:
            self.note_btn.config(text="TRIGGER NOTE", bg=accent_cyan, fg="#000000")

    def run(self):
        """Start ROS thread and Tkinter main loop."""
        signal.signal(signal.SIGINT, lambda sig, frame: self.on_close())
        self.ros_thread = threading.Thread(target=rclpy.spin, args=(self.node,), daemon=True)
        self.ros_thread.start()

        self.root.after(100, self.check_ros)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self.on_close()

    def check_ros(self):
        """Periodic check to see if ROS is still running."""
        if not rclpy.ok():
            self.on_close()
        else:
            self.root.after(100, self.check_ros)

    def on_close(self):
        """Clean shutdown of all resources."""
        self.node.get_logger().info("Shutting down GUI...")
        self.node.stream.stop()
        self.node.stream.close()
        self.root.quit()
        self.root.destroy()
        rclpy.shutdown()


def main():
    """Application entry point."""
    rclpy.init()
    node = SynthGUI()
    gui = MainGUI(node)
    gui.run()


if __name__ == '__main__':
    main()
