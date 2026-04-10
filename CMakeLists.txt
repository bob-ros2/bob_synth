cmake_minimum_required(VERSION 3.8)
project(bob_synth)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)

add_executable(synth_node src/synth_node.cpp)
target_include_directories(synth_node PRIVATE include)
ament_target_dependencies(synth_node rclcpp std_msgs)

install(TARGETS synth_node
  DESTINATION lib/${PROJECT_NAME})

install(PROGRAMS
  scripts/synth_gui.py
  scripts/audio_sink.py
  DESTINATION lib/${PROJECT_NAME}
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()