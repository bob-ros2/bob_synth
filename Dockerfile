FROM ros:humble-ros-base AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    python3-colcon-common-extensions \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /ros2_ws/src/bob_synth
COPY . .

# Build the package
WORKDIR /ros2_ws
RUN . /opt/ros/humble/setup.sh && \
    colcon build --packages-select bob_synth

# --- Final Image ---
FROM ros:humble-ros-core

WORKDIR /ros2_ws
COPY --from=builder /ros2_ws/install /ros2_ws/install

# Source the setup script
RUN echo "source /opt/ros/humble/setup.bash" >> ~/.bashrc
RUN echo "source /ros2_ws/install/setup.bash" >> ~/.bashrc

ENTRYPOINT ["/bin/bash", "-c", "source /ros2_ws/install/setup.bash && ros2 run bob_synth synth_node"]
