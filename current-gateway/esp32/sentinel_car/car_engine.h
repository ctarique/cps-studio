#pragma once

#include <stdint.h>
#include <string.h>

namespace carscps {

static constexpr uint8_t MOTOR_A_PIN_1 = 12;
static constexpr uint8_t MOTOR_A_PIN_2 = 13;
static constexpr uint8_t MOTOR_B_PIN_1 = 14;
static constexpr uint8_t MOTOR_B_PIN_2 = 15;

static constexpr uint32_t MOTOR_TEST_MS = 120;

inline void forceMotorsStopped() {
  pinMode(MOTOR_A_PIN_1, OUTPUT);
  pinMode(MOTOR_A_PIN_2, OUTPUT);
  pinMode(MOTOR_B_PIN_1, OUTPUT);
  pinMode(MOTOR_B_PIN_2, OUTPUT);

  digitalWrite(MOTOR_A_PIN_1, LOW);
  digitalWrite(MOTOR_A_PIN_2, LOW);
  digitalWrite(MOTOR_B_PIN_1, LOW);
  digitalWrite(MOTOR_B_PIN_2, LOW);
}

struct Engine {
  bool running = false;
  uint8_t activePin = 255;
  uint32_t started = 0;

  const char* state = "IDLE";
  const char* lastAction = "NONE";

  void init() {
    forceMotorsStopped();
    running = false;
    activePin = 255;
    state = "IDLE";
    lastAction = "NONE";
  }

  void tick(uint32_t now) {
    if (!running) return;

    if (uint32_t(now - started) >= MOTOR_TEST_MS) {
      forceMotorsStopped();
      running = false;
      activePin = 255;
      state = "COMPLETE";
    }
  }

  bool start(const char* action, uint32_t now) {
    tick(now);

    if (running) return false;

    forceMotorsStopped();

    uint8_t pin = 255;

    if (!strcmp(action, "MOTOR_A_TEST")) {
      // Compatibility alias for the previously validated
      // Motor A diagnostic direction.
      pin = MOTOR_A_PIN_1;
      lastAction = "MOTOR_A_TEST";

    } else if (!strcmp(action, "MOTOR_A_CW_TEST")) {
      pin = MOTOR_A_PIN_1;
      lastAction = "MOTOR_A_CW_TEST";

    } else if (!strcmp(action, "MOTOR_A_CCW_TEST")) {
      pin = MOTOR_A_PIN_2;
      lastAction = "MOTOR_A_CCW_TEST";

    } else if (!strcmp(action, "MOTOR_B_TEST")) {
      // Compatibility alias for the previously validated
      // Motor B diagnostic direction.
      pin = MOTOR_B_PIN_1;
      lastAction = "MOTOR_B_TEST";

    } else if (!strcmp(action, "MOTOR_B_CW_TEST")) {
      pin = MOTOR_B_PIN_2;
      lastAction = "MOTOR_B_CW_TEST";

    } else if (!strcmp(action, "MOTOR_B_CCW_TEST")) {
      pin = MOTOR_B_PIN_1;
      lastAction = "MOTOR_B_CCW_TEST";

    } else {
      return false;
    }

    activePin = pin;
    started = now;
    running = true;
    state = "RUNNING";

    digitalWrite(activePin, HIGH);

    return true;
  }

  void stop(bool commanded = false) {
    forceMotorsStopped();

    running = false;
    activePin = 255;
    state = "STOPPED";

    if (commanded) {
      lastAction = "STOP";
    }
  }

  bool motorAActive() const {
    return running && (
        activePin == MOTOR_A_PIN_1 ||
        activePin == MOTOR_A_PIN_2
    );
  }

  bool motorBActive() const {
    return running && (
        activePin == MOTOR_B_PIN_1 ||
        activePin == MOTOR_B_PIN_2
    );
  }
};

}  // namespace carscps
