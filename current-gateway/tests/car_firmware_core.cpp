#include <stdint.h>

#include <assert.h>
#include <stdio.h>
#include <string>


// Minimal Arduino GPIO model for host-only engine verification.
static constexpr uint8_t OUTPUT = 1;
static constexpr uint8_t LOW = 0;
static constexpr uint8_t HIGH = 1;

static uint8_t pinModes[40] = {};
static uint8_t pinLevels[40] = {};


void pinMode(uint8_t pin, uint8_t mode) {
  assert(pin < 40);
  pinModes[pin] = mode;
}


void digitalWrite(uint8_t pin, uint8_t value) {
  assert(pin < 40);
  assert(value == LOW || value == HIGH);
  pinLevels[pin] = value;
}


#include "../esp32/sentinel_car/car_engine.h"


static void assertAllMotorPinsLow() {
  assert(pinLevels[12] == LOW);
  assert(pinLevels[13] == LOW);
  assert(pinLevels[14] == LOW);
  assert(pinLevels[15] == LOW);
}


static void assertOnlyMotorAProbeActive() {
  assert(pinLevels[12] == HIGH);
  assert(pinLevels[13] == LOW);
  assert(pinLevels[14] == LOW);
  assert(pinLevels[15] == LOW);
}


static void assertOnlyMotorBProbeActive() {
  assert(pinLevels[12] == LOW);
  assert(pinLevels[13] == LOW);
  assert(pinLevels[14] == HIGH);
  assert(pinLevels[15] == LOW);
}


int main() {
  carscps::Engine engine;

  engine.init();

  for (uint8_t pin : {12, 13, 14, 15}) {
    assert(pinModes[pin] == OUTPUT);
  }

  assertAllMotorPinsLow();
  assert(!engine.running);
  assert(std::string(engine.state) == "IDLE");
  assert(std::string(engine.lastAction) == "NONE");


  // Motor A is fixed to the previously identified GPIO12
  // diagnostic direction.
  char mutableAction[] = "MOTOR_A_TEST";

  assert(engine.start(mutableAction, 100));
  assert(engine.running);
  assert(engine.motorAActive());
  assert(!engine.motorBActive());
  assertOnlyMotorAProbeActive();

  // The engine must not retain a pointer into the caller's
  // mutable HTTP request buffer.
  mutableAction[0] = 'X';

  assert(
      std::string(engine.lastAction) ==
      "MOTOR_A_TEST"
  );

  // 119 ms remains active.
  engine.tick(219);

  assert(engine.running);
  assertOnlyMotorAProbeActive();

  // A second test cannot begin while the first remains active.
  assert(
      !engine.start(
          "MOTOR_B_TEST",
          219
      )
  );

  assertOnlyMotorAProbeActive();

  // Exactly at the fixed 120 ms bound, outputs return LOW.
  engine.tick(220);

  assert(!engine.running);
  assert(!engine.motorAActive());
  assert(!engine.motorBActive());
  assertAllMotorPinsLow();

  assert(
      std::string(engine.state) ==
      "COMPLETE"
  );

  assert(
      std::string(engine.lastAction) ==
      "MOTOR_A_TEST"
  );


  // Motor B is independently restricted to GPIO14.
  assert(
      engine.start(
          "MOTOR_B_TEST",
          1000
      )
  );

  assert(!engine.motorAActive());
  assert(engine.motorBActive());
  assertOnlyMotorBProbeActive();

  engine.stop(true);

  assert(!engine.running);
  assertAllMotorPinsLow();

  assert(
      std::string(engine.state) ==
      "STOPPED"
  );

  assert(
      std::string(engine.lastAction) ==
      "STOP"
  );


  // Unsupported semantics cannot energize a motor.
  assert(
      !engine.start(
          "FORWARD",
          2000
      )
  );

  assert(!engine.running);
  assertAllMotorPinsLow();


  // Wi-Fi/fault-style uncommanded stop also restores all outputs.
  assert(
      engine.start(
          "MOTOR_A_TEST",
          3000
      )
  );

  assertOnlyMotorAProbeActive();

  engine.stop(false);

  assert(!engine.running);
  assertAllMotorPinsLow();


  // Unsigned elapsed-time arithmetic must remain safe across
  // millis() wrap.
  carscps::Engine wrap;
  wrap.init();

  const uint32_t start =
      0xfffffff0u;

  assert(
      wrap.start(
          "MOTOR_A_TEST",
          start
      )
  );

  wrap.tick(
      uint32_t(start + 119u)
  );

  assert(wrap.running);
  assertOnlyMotorAProbeActive();

  wrap.tick(
      uint32_t(start + 120u)
  );

  assert(!wrap.running);
  assertAllMotorPinsLow();


  puts(
      "PASS: CAR motor engine fixed pins, 120 ms bound, "
      "stop behavior, action storage, exclusivity, and clock-wrap checks"
  );

  return 0;
}
