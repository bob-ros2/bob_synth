ARG ROS_DISTRO=humble

# --- Builder Stage ---
FROM ros:${ROS_DISTRO}-ros-base AS builder
ARG ROS_DISTRO

# Install build dependencies
RUN apt-get update && apt-get install -y \
    python3-colcon-common-extensions \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /ros2_ws/src/bob_synth
COPY . .

# Build the package
WORKDIR /ros2_ws
RUN . /opt/ros/${ROS_DISTRO}/setup.sh && \
    colcon build --packages-select bob_synth

# --- Final Runtime Image ---
FROM ros:${ROS_DISTRO}-ros-core
ARG ROS_DISTRO

WORKDIR /ros2_ws

# Copy only the built artifacts from the builder stage
COPY --from=builder /ros2_ws/install /ros2_ws/install

# Install only minimal runtime dependencies if needed
# (bob_synth has no external binary deps currently)
RUN apt-get update && apt-get install -y \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Source both ROS and local setup
RUN echo "source /opt/ros/${ROS_DISTRO}/setup.bash" >> ~/.bashrc && \
    echo "source /ros2_ws/install/setup.bash" >> ~/.bashrc

# Entrypoint to run the node directly
ENTRYPOINT ["/bin/bash", "-c", "source /ros2_ws/install/setup.bash && ros2 run bob_synth synth_node"]
