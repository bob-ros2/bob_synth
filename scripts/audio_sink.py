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

"""Headless Audio Sink for Bob Synth."""

import signal
import sys

import numpy as np
import rclpy
from rclpy.node import Node
import sounddevice as sd
from std_msgs.msg import Int16MultiArray


class AudioSink(Node):
    """Headless node for playing ROS 2 audio streams via ALSA."""

    def __init__(self):
        super().__init__('audio_sink')

        # Audio parameters
        self.sample_rate = 44100
        self.channels = 2
        self.chunk_size = 1024

        # Subscription to standard audio out
        self.subscription = self.create_subscription(
            Int16MultiArray,
            '/audio_out',
            self.audio_callback,
            10)

        # Open non-blocking output stream
        try:
            self.stream = sd.OutputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype='int16',
                blocksize=self.chunk_size
            )
            self.stream.start()
            self.get_logger().info("Audio Sink started (Headless Mode)")
        except Exception as e:
            self.get_logger().error(f"Failed to open audio device: {e}")
            sys.exit(1)

    def audio_callback(self, msg):
        """Play incoming PCM data."""
        try:
            data = np.array(msg.data, dtype=np.int16).reshape(-1, self.channels)
            self.stream.write(data)
        except Exception as e:
            self.get_logger().warn(f"Audio playback error: {e}")


def main(args=None):
    """Node entry point."""
    rclpy.init(args=args)
    node = AudioSink()

    def signal_handler(sig, frame):
        node.get_logger().info("Shutting down Audio Sink...")
        node.stream.stop()
        node.stream.close()
        node.destroy_node()
        rclpy.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
