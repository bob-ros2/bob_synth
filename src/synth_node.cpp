// Copyright 2026 Bob Ros
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#include <fcntl.h>
#include <unistd.h>

#include <algorithm>
#include <cmath>
#include <fstream>
#include <sstream>
#include <atomic>
#include <condition_variable>
#include <mutex>
#include <queue>
#include <string>
#include <thread>
#include <vector>

#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/int16_multi_array.hpp>
#include <std_msgs/msg/string.hpp>

class SynthNode : public rclcpp::Node
{
public:
  SynthNode()
  : Node("bob_synth")
  {
    callback_group_ = this->create_callback_group(
      rclcpp::CallbackGroupType::Reentrant);

    // --- Parameter Declaration with Env Var Support (SYNTH_*) ---
    auto declare_with_env = [this](const std::string & name, auto default_val) {
        std::string env_key = "SYNTH_" + name;
        std::transform(env_key.begin(), env_key.end(), env_key.begin(), ::toupper);

        char * env_val = std::getenv(env_key.c_str());
        using T = decltype(default_val);

        if (env_val) {
          if constexpr (std::is_same_v<T, std::string>) {
            return this->declare_parameter<T>(name, std::string(env_val));
          } else if constexpr (std::is_same_v<T, double>) {
            return this->declare_parameter<T>(name, std::stod(env_val));
          } else if constexpr (std::is_same_v<T, int>) {
            return this->declare_parameter<T>(name, std::stoi(env_val));
          } else if constexpr (std::is_same_v<T, bool>) {
            std::string s(env_val);
            bool b = (s == "true" || s == "1" || s == "TRUE" || s == "ON");
            return this->declare_parameter<T>(name, b);
          }
        }
        return this->declare_parameter<T>(name, default_val);
      };

    // Parameters
    declare_with_env("frequency", 440.0);
    declare_with_env("amplitude", 0.5);
    declare_with_env("waveform", std::string("sine"));
    declare_with_env("mod_frequency", 5.0);
    declare_with_env("mod_depth", 0.0);
    this->declare_parameter("filter_cutoff", 1000.0);
    this->declare_parameter("filter_resonance", 0.0);
    declare_with_env("note_on", false);
    declare_with_env("attack", 0.1);
    declare_with_env("decay", 0.1);
    declare_with_env("sustain", 0.7);
    declare_with_env("release", 0.2);
    declare_with_env("sample_rate", 44100);
    declare_with_env("channels", 2);
    declare_with_env("chunk_ms", 20);
    this->declare_parameter("json_config", "");

    // Publisher
    publisher_ = this->create_publisher<std_msgs::msg::Int16MultiArray>(
      "audio_out", 10);

    // JSON Config Subscriber
    auto sub_opt = rclcpp::SubscriptionOptions();
    sub_opt.callback_group = callback_group_;
    config_sub_ = this->create_subscription<std_msgs::msg::String>(
      "config_in", 10,
      std::bind(&SynthNode::jsonConfigCallback, this, std::placeholders::_1),
      sub_opt);

    // Initial state sync
    syncInternalState();

    // Load initial JSON config if provided
    std::string config_path = this->get_parameter("json_config").as_string();
    if (!config_path.empty()) {
      std::ifstream f(config_path);
      if (f.is_open()) {
        std::stringstream buffer;
        buffer << f.rdbuf();
        applyJsonConfig(buffer.str());
        RCLCPP_INFO(this->get_logger(), "Loaded initial config from: %s", config_path.c_str());
      } else {
        RCLCPP_ERROR(this->get_logger(), "Could not open json_config file: %s", config_path.c_str());
      }
    }

    // Timer
    int chunk_ms = this->get_parameter("chunk_ms").as_int();
    timer_ = this->create_wall_timer(
      std::chrono::milliseconds(chunk_ms),
      std::bind(&SynthNode::generateAudio, this),
      callback_group_);

    param_callback_ = this->add_on_set_parameters_callback(
      std::bind(&SynthNode::parametersCallback, this, std::placeholders::_1));

    RCLCPP_INFO(this->get_logger(), "Bob Synth v0.1.0 started");
    RCLCPP_INFO(
      this->get_logger(), "Resolved Output Topic: %s",
      publisher_->get_topic_name());
  }

  ~SynthNode()
  {
  }

private:
  void syncInternalState()
  {
    std::lock_guard<std::mutex> lock(audio_mutex_);
    frequency_ = this->get_parameter("frequency").as_double();
    amplitude_ = this->get_parameter("amplitude").as_double();
    waveform_ = this->get_parameter("waveform").as_string();
    attack_ = this->get_parameter("attack").as_double();
    decay_ = this->get_parameter("decay").as_double();
    sustain_ = this->get_parameter("sustain").as_double();
    release_ = this->get_parameter("release").as_double();
    mod_frequency_ = this->get_parameter("mod_frequency").as_double();
    mod_depth_ = this->get_parameter("mod_depth").as_double();
    sample_rate_ = this->get_parameter("sample_rate").as_int();
    channels_ = this->get_parameter("channels").as_int();
    note_on_ = this->get_parameter("note_on").as_bool();
    filter_cutoff_ = this->get_parameter("filter_cutoff").as_double();
    filter_resonance_ = this->get_parameter("filter_resonance").as_double();

    int chunk_ms = this->get_parameter("chunk_ms").as_int();
    samples_per_chunk_ = (sample_rate_ * chunk_ms) / 1000;
  }

  void applyJsonConfig(const std::string & json)
  {
    std::vector<rclcpp::Parameter> updates;

    auto extract = [&](const std::string & key, bool is_str = false) {
        size_t p = json.find("\"" + key + "\"");
        if (p == std::string::npos) {return;}
        size_t v_p = json.find(":", p) + 1;
        while (v_p < json.size() && (json[v_p] == ' ' || json[v_p] == '\"')) {v_p++;}
        size_t e_p = json.find_first_of(",}\"", v_p);
        std::string val = json.substr(v_p, e_p - v_p);

        if (is_str) {
          updates.push_back(rclcpp::Parameter(key, val));
        } else if (val == "true" || val == "false") {
          updates.push_back(rclcpp::Parameter(key, val == "true"));
        } else {
          try {
            updates.push_back(rclcpp::Parameter(key, std::stod(val)));
          } catch (...) {}
        }
      };

    extract("frequency"); extract("amplitude"); extract("waveform", true);
    extract("mod_frequency"); extract("mod_depth");
    extract("filter_cutoff"); extract("filter_resonance");
    extract("note_on"); extract("attack"); extract("decay");
    extract("sustain"); extract("release");

    if (!updates.empty()) {this->set_parameters(updates);}
  }

  void jsonConfigCallback(const std_msgs::msg::String::SharedPtr msg)
  {
    applyJsonConfig(msg->data);
  }

  void generateAudio()
  {
    std::lock_guard<std::mutex> lock(audio_mutex_);
    // We always generate audio (even silence) to keep the FIFO stream stable and timed correctly.
    auto msg = std_msgs::msg::Int16MultiArray();
    msg.data.resize(samples_per_chunk_ * channels_);
    double dt = 1.0 / sample_rate_;

    for (int i = 0; i < samples_per_chunk_; i++) {
      updateEnvelope(dt);

      mod_phase_ += 2.0 * M_PI * mod_frequency_ * dt;
      if (mod_phase_ > 2.0 * M_PI) {mod_phase_ -= 2.0 * M_PI;}

      double current_freq = frequency_ + (sin(mod_phase_) * mod_depth_);
      phase_ += 2.0 * M_PI * current_freq * dt;
      if (phase_ > 2.0 * M_PI) {phase_ -= 2.0 * M_PI;}

      double s = 0.0;
      if (waveform_ == "sine") {
        s = sin(phase_);
      } else if (waveform_ == "square") {
        s = sin(phase_) > 0 ? 1.0 : -1.0;
      } else if (waveform_ == "triangle") {
        s = asin(sin(phase_)) * (2.0 / M_PI);
      } else if (waveform_ == "sawtooth" || waveform_ == "saw") {
        s = (fmod(phase_, 2.0 * M_PI) / M_PI) - 1.0;
      }

      double sample = s * amplitude_ * env_level_;

      // --- Parameter Smoothing (Filter Cutoff) ---
      // Smoothly interpolate towards target cutoff to avoid zipper noise
      current_filter_cutoff_ += (filter_cutoff_ - current_filter_cutoff_) * 0.01;
      double safe_cutoff = std::clamp(current_filter_cutoff_, 20.0, 16000.0);

      // --- Precise State Variable Filter (SVF) ---
      // f = 2 * sin(pi * freq / sr) - approximation for low frequencies
      double f = 2.0 * std::sin(M_PI * safe_cutoff / sample_rate_);
      double q = 1.0 - filter_resonance_;  // Normal resonance mapping

      // SVF Core logic
      filter_h_ = sample - filter_l_ - q * filter_b_;
      filter_b_ = f * filter_h_ + filter_b_;
      filter_l_ = f * filter_b_ + filter_l_;

      // Output (Lowpass)
      sample = filter_l_;

      int16_t pcm = static_cast<int16_t>(std::clamp(sample, -1.0, 1.0) * 32767.0);
      for (int ch = 0; ch < channels_; ch++) {msg.data[i * channels_ + ch] = pcm;}
    }

    publisher_->publish(msg);
  }

  void updateEnvelope(double dt)
  {
    switch (adsr_phase_) {
      case ATTACK:
        env_level_ += dt / std::max(0.001, attack_);
        if (env_level_ >= 1.0) {
          env_level_ = 1.0;
          adsr_phase_ = DECAY;
        }
        break;
      case DECAY:
        if (env_level_ > sustain_) {
          env_level_ -= dt / std::max(0.001, decay_) * (1.0 - sustain_);
          if (env_level_ <= sustain_) {
            env_level_ = sustain_;
            adsr_phase_ = SUSTAIN;
          }
        } else {
          env_level_ = sustain_;
          adsr_phase_ = SUSTAIN;
        }
        break;
      case SUSTAIN:
        env_level_ = sustain_;
        if (!note_on_) {
          adsr_phase_ = RELEASE;
        }
        break;
      case RELEASE:
        env_level_ -= dt / std::max(0.001, release_);
        if (env_level_ <= 0.0) {
          env_level_ = 0.0;
        }
        break;
    }
    env_level_ = std::max(0.0, std::min(1.0, env_level_));
  }

  rcl_interfaces::msg::SetParametersResult parametersCallback(
    const std::vector<rclcpp::Parameter> & params)
  {
    {
      std::lock_guard<std::mutex> lock(audio_mutex_);
      for (const auto & p : params) {
        if (p.get_name() == "frequency") {
          frequency_ = p.as_double();
        } else if (p.get_name() == "amplitude") {
          amplitude_ = p.as_double();
        } else if (p.get_name() == "waveform") {
          waveform_ = p.as_string();
        } else if (p.get_name() == "attack") {
          attack_ = p.as_double();
        } else if (p.get_name() == "decay") {
          decay_ = p.as_double();
        } else if (p.get_name() == "sustain") {
          sustain_ = p.as_double();
        } else if (p.get_name() == "release") {
          release_ = p.as_double();
        } else if (p.get_name() == "mod_frequency") {
          mod_frequency_ = p.as_double();
        } else if (p.get_name() == "mod_depth") {
          mod_depth_ = p.as_double();
        } else if (p.get_name() == "filter_cutoff") {
          filter_cutoff_ = p.as_double();
        } else if (p.get_name() == "filter_resonance") {
          filter_resonance_ = p.as_double();
        } else if (p.get_name() == "note_on") {
          if (p.as_bool() && !note_on_) {
            note_on_ = true; adsr_phase_ = ATTACK;
          } else if (!p.as_bool() && note_on_) {
            note_on_ = false; adsr_phase_ = RELEASE;
          }
        }
      }
    }

    rcl_interfaces::msg::SetParametersResult res;
    res.successful = true;
    return res;
  }

  rclcpp::Publisher<std_msgs::msg::Int16MultiArray>::SharedPtr publisher_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr config_sub_;
  rclcpp::TimerBase::SharedPtr timer_;
  rclcpp::CallbackGroup::SharedPtr callback_group_;
  rclcpp::node_interfaces::OnSetParametersCallbackHandle::SharedPtr param_callback_;
  double frequency_, amplitude_, attack_, decay_, sustain_, release_;
  double mod_frequency_, mod_depth_;
  std::string waveform_;
  int sample_rate_, channels_, samples_per_chunk_;
  double filter_cutoff_;
  double current_filter_cutoff_ = 1000.0;
  double filter_resonance_;
  double filter_l_ = 0.0, filter_b_ = 0.0, filter_h_ = 0.0;
  bool note_on_ = false;
  double phase_ = 0.0, mod_phase_ = 0.0, env_level_ = 0.0;
  std::mutex audio_mutex_;

  enum ADSRPhase {ATTACK, DECAY, SUSTAIN, RELEASE};
  ADSRPhase adsr_phase_ = RELEASE;
};

int main(int argc, char * argv[])
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<SynthNode>();
  rclcpp::executors::MultiThreadedExecutor executor;
  executor.add_node(node);
  executor.spin();
  rclcpp::shutdown();
  return 0;
}
