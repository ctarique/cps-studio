#include <Arduino.h>
#include <WiFi.h>
#include <Network.h>
#include <esp_camera.h>
#include <esp_system.h>
#include <lwip/sockets.h>
#include <mbedtls/md.h>
#include <mbedtls/sha256.h>

#include "car_engine.h"
#include "response.h"

#if __has_include("sentinel_car_config.local.h")
#include "sentinel_car_config.local.h"
#else
#include "sentinel_car_config.example.h"
#endif


static constexpr char DEVICE_ID[] = "CAR-01";
static constexpr char FIRMWARE_ID[] =
    "car01-authenticated-0.1";

static constexpr uint8_t LDR_32_PIN = 32;
static constexpr uint8_t LDR_33_PIN = 33;


// WROVER-KIT camera mapping validated during CAR-01 discovery.
static constexpr int CAMERA_PWDN  = -1;
static constexpr int CAMERA_RESET = -1;
static constexpr int CAMERA_XCLK  = 21;
static constexpr int CAMERA_SIOD  = 26;
static constexpr int CAMERA_SIOC  = 27;

static constexpr int CAMERA_Y9    = 35;
static constexpr int CAMERA_Y8    = 34;
static constexpr int CAMERA_Y7    = 39;
static constexpr int CAMERA_Y6    = 36;
static constexpr int CAMERA_Y5    = 19;
static constexpr int CAMERA_Y4    = 18;
static constexpr int CAMERA_Y3    = 5;
static constexpr int CAMERA_Y2    = 4;

static constexpr int CAMERA_VSYNC = 25;
static constexpr int CAMERA_HREF  = 23;
static constexpr int CAMERA_PCLK  = 22;


NetworkServer server(80);
NetworkClient peer;

IPAddress gatewayIP;

carscps::Engine engine;

char bootID[33] = {};
char runID[33] =
    "00000000000000000000000000000000";

uint8_t key[32] = {};

uint32_t sequence = 1;
uint32_t clientStarted = 0;

bool configured = false;
bool listening = false;
bool parsedHeaders = false;
bool cameraReady = false;

char headerBuf[1537] = {};
char bodyBuf[257] = {};
char signature[65] = {};
char target[100] = {};
char method[5] = {};

size_t headerUsed = 0;
size_t bodyUsed = 0;
size_t bodyLength = 0;


void toHex(
    const uint8_t* input,
    size_t count,
    char* output) {

  static const char* alphabet =
      "0123456789abcdef";

  for (size_t i = 0; i < count; ++i) {
    output[2 * i] =
        alphabet[input[i] >> 4];

    output[2 * i + 1] =
        alphabet[input[i] & 15];
  }

  output[count * 2] = 0;
}


bool lowercaseHex(
    const char* text,
    size_t count) {

  if (strlen(text) != count) {
    return false;
  }

  for (size_t i = 0; i < count; ++i) {
    const char c = text[i];

    if (
        !(
          (c >= '0' && c <= '9') ||
          (c >= 'a' && c <= 'f')
        )
    ) {
      return false;
    }
  }

  return true;
}


bool decimalNumber(
    const char* text,
    uint32_t& value,
    uint32_t maximum) {

  if (!*text) return false;

  if (*text == '0' && text[1]) {
    return false;
  }

  uint32_t parsed = 0;

  for (; *text; ++text) {
    if (*text < '0' || *text > '9') {
      return false;
    }

    const uint32_t digit =
        uint32_t(*text - '0');

    if (
        parsed >
        (maximum - digit) / 10
    ) {
      return false;
    }

    parsed = parsed * 10 + digit;

    if (parsed > maximum) {
      return false;
    }
  }

  value = parsed;
  return true;
}


void hashText(
    const char* data,
    char* result) {

  uint8_t raw[32] = {};

  mbedtls_sha256(
      reinterpret_cast<const unsigned char*>(data),
      strlen(data),
      raw,
      0
  );

  toHex(raw, 32, result);
}


void hashBytes(
    const uint8_t* data,
    size_t length,
    char* result) {

  uint8_t raw[32] = {};

  mbedtls_sha256(
      data,
      length,
      raw,
      0
  );

  toHex(
      raw,
      32,
      result
  );
}


void mac(
    const String& context,
    const char* data,
    char* result) {

  mbedtls_md_context_t ctx;
  mbedtls_md_init(&ctx);

  const mbedtls_md_info_t* info =
      mbedtls_md_info_from_type(
          MBEDTLS_MD_SHA256
      );

  uint8_t raw[32] = {};

  if (
      mbedtls_md_setup(
          &ctx,
          info,
          1
      ) != 0
  ) {
    result[0] = 0;
    return;
  }

  mbedtls_md_hmac_starts(
      &ctx,
      key,
      sizeof(key)
  );

  mbedtls_md_hmac_update(
      &ctx,
      reinterpret_cast<const unsigned char*>(
          context.c_str()
      ),
      context.length()
  );

  mbedtls_md_hmac_update(
      &ctx,
      reinterpret_cast<const unsigned char*>(data),
      strlen(data)
  );

  mbedtls_md_hmac_finish(
      &ctx,
      raw
  );

  mbedtls_md_free(&ctx);

  toHex(raw, 32, result);
}


bool equalSignature(
    const char* expected,
    const char* supplied) {

  if (
      !lowercaseHex(expected, 64) ||
      !lowercaseHex(supplied, 64)
  ) {
    return false;
  }

  uint8_t difference = 0;

  for (int i = 0; i < 64; ++i) {
    difference |=
        expected[i] ^ supplied[i];
  }

  return difference == 0;
}


uint16_t averageAnalog(
    uint8_t pin) {

  uint32_t total = 0;

  for (uint8_t i = 0; i < 16; ++i) {
    total += analogRead(pin);
    delayMicroseconds(250);

    // Keep the bounded actuator timer serviced even during ADC sampling.
    engine.tick(millis());
  }

  return static_cast<uint16_t>(
      total / 16
  );
}


int boundedRSSI() {
  int value = WiFi.RSSI();

  if (value < -127) value = -127;
  if (value > 0) value = 0;

  return value;
}


void closePeer() {
  peer.stop();

  headerUsed = 0;
  bodyUsed = 0;
  bodyLength = 0;
  parsedHeaders = false;
}


void sendResponse(
    const char* response,
    int length) {

  if (length > 0) {
    carscps::sendOnce(
        response,
        size_t(length),
        [](const char* bytes, size_t count) {
          return send(
              peer.fd(),
              bytes,
              count,
              MSG_DONTWAIT
          );
        }
    );
  }

  closePeer();
}


bool sendBytesBounded(
    const uint8_t* bytes,
    size_t count) {

  if (
      !bytes ||
      count == 0
  ) {
    return false;
  }

  const uint32_t started =
      millis();

  size_t sent = 0;

  while (sent < count) {
    engine.tick(millis());

    if (
        uint32_t(
            millis() - started
        ) > 1000
    ) {
      return false;
    }

    const int written =
        send(
            peer.fd(),
            bytes + sent,
            count - sent,
            MSG_DONTWAIT
        );

    if (written > 0) {
      sent +=
          size_t(written);

      continue;
    }

    delay(1);
  }

  return true;
}


void reject(
    int code = 400) {

  char response[
      carscps::RESPONSE_CAPACITY
  ];

  const int length = snprintf(
      response,
      sizeof(response),
      "HTTP/1.1 %d Rejected\r\n"
      "Connection: close\r\n"
      "Content-Length: 0\r\n"
      "\r\n",
      code
  );

  sendResponse(
      response,
      length
  );
}


void replyCamera(
    const char* nonce) {

  engine.tick(millis());

  if (
      engine.motorAActive() ||
      engine.motorBActive()
  ) {
    reject(409);
    return;
  }

  if (!cameraReady) {
    reject(503);
    return;
  }

  camera_fb_t* frame =
      esp_camera_fb_get();

  engine.tick(millis());

  if (
      !frame ||
      !frame->buf ||
      frame->len == 0 ||
      frame->len > 65536
  ) {
    if (frame) {
      esp_camera_fb_return(
          frame
      );
    }

    reject(503);
    return;
  }

  char digest[65] = {};

  hashBytes(
      frame->buf,
      frame->len,
      digest
  );

  const String context =
      String("CAMERA\n") +
      String(nonce) +
      "\n" +
      String(digest) +
      "\n" +
      String(
          static_cast<unsigned long>(
              frame->len
          )
      ) +
      "\n";

  char signedFrame[65] = {};

  mac(
      context,
      "",
      signedFrame
  );

  if (!signedFrame[0]) {
    esp_camera_fb_return(
        frame
    );

    reject(503);
    return;
  }

  char response[512] = {};

  const int responseLength =
      snprintf(
          response,
          sizeof(response),
          "HTTP/1.1 200 OK\r\n"
          "Content-Type: image/jpeg\r\n"
          "Cache-Control: no-store\r\n"
          "Connection: close\r\n"
          "Content-Length: %u\r\n"
          "X-Sentinel-Frame-SHA256: %s\r\n"
          "X-Sentinel-Signature: %s\r\n"
          "\r\n",
          unsigned(frame->len),
          digest,
          signedFrame
      );

  if (
      responseLength <= 0 ||
      responseLength >=
          int(sizeof(response))
  ) {
    esp_camera_fb_return(
        frame
    );

    reject(503);
    return;
  }

  const bool headerSent =
      sendBytesBounded(
          reinterpret_cast<const uint8_t*>(
              response
          ),
          size_t(responseLength)
      );

  if (headerSent) {
    sendBytesBounded(
        frame->buf,
        frame->len
    );
  }

  esp_camera_fb_return(
      frame
  );

  /*
   * If the binary body is only partially transmitted,
   * do not attempt to send a second HTTP response.
   */
  closePeer();
}


void reply(
    const String& context) {

  engine.tick(millis());

  const uint16_t ldr32 =
      averageAnalog(LDR_32_PIN);

  const uint16_t ldr33 =
      averageAnalog(LDR_33_PIN);

  engine.tick(millis());

  const int rssi = boundedRSSI();

  char result[385] = {};
  char signedResult[65] = {};

  snprintf(
      result,
      sizeof(result),
      "SCPS1|CAR|%s|%lu|%s|%s|%s|%d|%d|%u|%u|%d|%d|DEVICE",
      bootID,
      static_cast<unsigned long>(sequence),
      runID,
      engine.state,
      engine.lastAction,
      engine.motorAActive() ? 1 : 0,
      engine.motorBActive() ? 1 : 0,
      static_cast<unsigned>(ldr32),
      static_cast<unsigned>(ldr33),
      cameraReady ? 1 : 0,
      rssi
  );

  mac(
      context,
      result,
      signedResult
  );

  if (!signedResult[0]) {
    reject(503);
    return;
  }

  char response[
      carscps::RESPONSE_CAPACITY
  ];

  const int length = snprintf(
      response,
      sizeof(response),
      "HTTP/1.1 200 OK\r\n"
      "Content-Type: text/plain\r\n"
      "Cache-Control: no-store\r\n"
      "Connection: close\r\n"
      "Content-Length: %u\r\n"
      "X-Sentinel-Signature: %s\r\n"
      "\r\n"
      "%s",
      unsigned(strlen(result)),
      signedResult,
      result
  );

  sendResponse(
      response,
      length
  );
}


bool parseHeaders() {
  headerBuf[headerUsed] = 0;

  char* firstEnd =
      strstr(headerBuf, "\r\n");

  if (!firstEnd) {
    return false;
  }

  *firstEnd = 0;

  char protocol[12] = {};
  char extra[2] = {};

  if (
      sscanf(
          headerBuf,
          "%4s %99s %11s %1s",
          method,
          target,
          protocol,
          extra
      ) != 3 ||
      strcmp(protocol, "HTTP/1.1")
  ) {
    return false;
  }

  bool hasLength = false;
  bool hasSignature = false;

  signature[0] = 0;

  char* cursor = firstEnd + 2;
  int count = 0;

  while (*cursor) {
    char* end =
        strstr(cursor, "\r\n");

    if (!end) {
      return false;
    }

    *end = 0;

    if (!*cursor) {
      break;
    }

    if (++count > 16) {
      return false;
    }

    char* colon =
        strchr(cursor, ':');

    if (!colon) {
      return false;
    }

    *colon = 0;

    for (char* keyName = cursor;
         *keyName;
         ++keyName) {

      if (
          *keyName >= 'A' &&
          *keyName <= 'Z'
      ) {
        *keyName += 32;
      }
    }

    char* value = colon + 1;

    while (*value == ' ') {
      ++value;
    }

    if (!strcmp(cursor, "content-length")) {
      uint32_t length = 0;

      if (
          hasLength ||
          !decimalNumber(
              value,
              length,
              256
          )
      ) {
        return false;
      }

      hasLength = true;
      bodyLength = length;

    } else if (
        !strcmp(
            cursor,
            "x-sentinel-signature"
        )
    ) {
      if (
          hasSignature ||
          !lowercaseHex(value, 64)
      ) {
        return false;
      }

      hasSignature = true;
      strcpy(signature, value);

    } else if (
        !strcmp(cursor, "transfer-encoding") ||
        !strcmp(cursor, "expect")
    ) {
      return false;
    }

    cursor = end + 2;
  }

  if (!strcmp(method, "GET")) {
    return !hasSignature &&
        bodyLength == 0;
  }

  return (
      !strcmp(method, "POST") &&
      hasLength &&
      bodyLength > 0 &&
      hasSignature
  );
}


void dispatch() {
  bodyBuf[bodyUsed] = 0;

  if (!strcmp(method, "GET")) {
    if (!strcmp(target, "/health")) {
      const char* diagnostic =
          "{\"service\":\"Sentinel-CPS\","
          "\"device_id\":\"CAR-01\","
          "\"protocol\":1,"
          "\"diagnostic_only\":true}";

      char response[
          carscps::RESPONSE_CAPACITY
      ];

      const int length = snprintf(
          response,
          sizeof(response),
          "HTTP/1.1 200 OK\r\n"
          "Content-Type: application/json\r\n"
          "Cache-Control: no-store\r\n"
          "Connection: close\r\n"
          "Content-Length: %u\r\n"
          "\r\n"
          "%s",
          unsigned(strlen(diagnostic)),
          diagnostic
      );

      sendResponse(
          response,
          length
      );

      return;
    }

    const char* cameraPrefix =
        "/v1/camera?nonce=";

    if (
        !strncmp(
            target,
            cameraPrefix,
            strlen(cameraPrefix)
        )
    ) {
      const char* cameraNonce =
          target +
          strlen(cameraPrefix);

      if (
          !lowercaseHex(
              cameraNonce,
              32
          )
      ) {
        reject(404);
        return;
      }

      replyCamera(
          cameraNonce
      );

      return;
    }

    const char* prefix =
        "/v1/status?nonce=";

    if (
        strncmp(
            target,
            prefix,
            strlen(prefix)
        ) ||
        !lowercaseHex(
            target + strlen(prefix),
            32
        )
    ) {
      reject(404);
      return;
    }

    reply(
        String("STATUS\n") +
        String(target + strlen(prefix)) +
        "\n"
    );

    return;
  }

  if (strcmp(target, "/v1/work")) {
    reject(404);
    return;
  }

  char expected[65] = {};
  char requestHash[65] = {};

  mac(
      "POST\n/v1/work\n",
      bodyBuf,
      expected
  );

  if (
      !equalSignature(
          expected,
          signature
      )
  ) {
    reject(403);
    return;
  }

  hashText(
      bodyBuf,
      requestHash
  );

  char* fields[6] = {};
  fields[0] = bodyBuf;

  int count = 1;

  for (char* cursor = bodyBuf;
       *cursor;
       ++cursor) {

    if (*cursor == '|') {
      *cursor = 0;

      if (count == 6) {
        reject();
        return;
      }

      fields[count++] =
          cursor + 1;
    }
  }

  if (
      count != 6 ||
      strcmp(fields[0], "SCPS1") ||
      strcmp(fields[1], "CAR") ||
      strcmp(fields[2], bootID) ||
      !lowercaseHex(fields[4], 32)
  ) {
    reject(409);
    return;
  }

  uint32_t requestedSequence = 0;

  if (
      !decimalNumber(
          fields[3],
          requestedSequence,
          99999998
      ) ||
      requestedSequence != sequence
  ) {
    reject(409);
    return;
  }

  const char* requestedRunID =
      fields[4];

  const char* action =
      fields[5];

  bool accepted = false;

  engine.tick(millis());

  if (
      !strcmp(
          action,
          "MOTOR_A_TEST"
      ) ||
      !strcmp(
          action,
          "MOTOR_A_CW_TEST"
      ) ||
      !strcmp(
          action,
          "MOTOR_A_CCW_TEST"
      ) ||
      !strcmp(
          action,
          "MOTOR_B_TEST"
      ) ||
      !strcmp(
          action,
          "MOTOR_B_CW_TEST"
      ) ||
      !strcmp(
          action,
          "MOTOR_B_CCW_TEST"
      )
  ) {
    accepted =
        engine.start(
            action,
            millis()
        );

  } else if (
      !strcmp(
          action,
          "STOP"
      )
  ) {
    engine.stop(true);
    accepted = true;
  }

  if (!accepted) {
    reject(409);
    return;
  }

  strcpy(
      runID,
      requestedRunID
  );

  ++sequence;

  reply(
      String("RESULT\n") +
      String(requestHash) +
      "\n"
  );
}


void pollClient() {
  engine.tick(millis());

  if (!peer) {
    peer = server.accept();

    if (!peer) {
      return;
    }

    if (
        peer.remoteIP() !=
        gatewayIP
    ) {
      closePeer();
      return;
    }

    peer.setTimeout(50);

    clientStarted = millis();
    headerUsed = 0;
    bodyUsed = 0;
    bodyLength = 0;
    parsedHeaders = false;
  }

  engine.tick(millis());

  if (
      uint32_t(
          millis() - clientStarted
      ) > 1000
  ) {
    closePeer();
    return;
  }

  int budget = 256;

  while (
      peer.available() &&
      budget-- > 0
  ) {
    engine.tick(millis());

    const int value =
        peer.read();

    if (value < 0) {
      break;
    }

    if (!parsedHeaders) {
      if (
          headerUsed == 1536 ||
          value == 0 ||
          value > 126 ||
          (
            value < 32 &&
            value != '\r' &&
            value != '\n'
          )
      ) {
        reject();
        return;
      }

      headerBuf[headerUsed++] =
          char(value);

      if (
          headerUsed >= 4 &&
          !memcmp(
              headerBuf +
              headerUsed - 4,
              "\r\n\r\n",
              4
          )
      ) {
        if (!parseHeaders()) {
          reject();
          return;
        }

        parsedHeaders = true;

        if (bodyLength == 0) {
          dispatch();
          return;
        }
      }

    } else {
      if (
          bodyUsed == 256 ||
          value < 32 ||
          value > 126
      ) {
        reject();
        return;
      }

      bodyBuf[bodyUsed++] =
          char(value);

      if (bodyUsed == bodyLength) {
        dispatch();
        return;
      }
    }
  }

  engine.tick(millis());
}


bool initializeCamera() {
  carscps::forceMotorsStopped();

  camera_config_t config = {};

  config.ledc_channel =
      LEDC_CHANNEL_0;

  config.ledc_timer =
      LEDC_TIMER_0;

  config.pin_d0 = CAMERA_Y2;
  config.pin_d1 = CAMERA_Y3;
  config.pin_d2 = CAMERA_Y4;
  config.pin_d3 = CAMERA_Y5;
  config.pin_d4 = CAMERA_Y6;
  config.pin_d5 = CAMERA_Y7;
  config.pin_d6 = CAMERA_Y8;
  config.pin_d7 = CAMERA_Y9;

  config.pin_xclk =
      CAMERA_XCLK;

  config.pin_pclk =
      CAMERA_PCLK;

  config.pin_vsync =
      CAMERA_VSYNC;

  config.pin_href =
      CAMERA_HREF;

  config.pin_sccb_sda =
      CAMERA_SIOD;

  config.pin_sccb_scl =
      CAMERA_SIOC;

  config.pin_pwdn =
      CAMERA_PWDN;

  config.pin_reset =
      CAMERA_RESET;

  config.xclk_freq_hz =
      20000000;

  config.pixel_format =
      PIXFORMAT_JPEG;

  config.frame_size =
      FRAMESIZE_QVGA;

  config.jpeg_quality = 12;
  config.fb_count = 1;

  config.grab_mode =
      CAMERA_GRAB_WHEN_EMPTY;

  config.fb_location =
      psramFound()
      ? CAMERA_FB_IN_PSRAM
      : CAMERA_FB_IN_DRAM;

  const esp_err_t result =
      esp_camera_init(&config);

  cameraReady =
      result == ESP_OK;

  carscps::forceMotorsStopped();

  return cameraReady;
}


bool configurationValid() {
  if (
      strlen(SENTINEL_WIFI_SSID) < 1 ||
      strlen(SENTINEL_WIFI_SSID) > 32 ||
      strlen(SENTINEL_WIFI_PASSWORD) < 8 ||
      strlen(SENTINEL_WIFI_PASSWORD) > 63 ||
      !gatewayIP.fromString(
          SENTINEL_GATEWAY_IP
      ) ||
      !lowercaseHex(
          SENTINEL_CAR_DEVICE_KEY,
          64
      )
  ) {
    return false;
  }

  if (
      !(
        gatewayIP[0] == 10 ||
        (
          gatewayIP[0] == 172 &&
          gatewayIP[1] >= 16 &&
          gatewayIP[1] <= 31
        ) ||
        (
          gatewayIP[0] == 192 &&
          gatewayIP[1] == 168
        )
      )
  ) {
    return false;
  }

  for (int i = 0; i < 32; ++i) {
    char pair[3] = {
        SENTINEL_CAR_DEVICE_KEY[i * 2],
        SENTINEL_CAR_DEVICE_KEY[
            i * 2 + 1
        ],
        0
    };

    key[i] =
        strtoul(
            pair,
            nullptr,
            16
        );
  }

  return true;
}


void setup() {
  // First application-level action: force every motor-driver
  // input to the physically stopped state.
  carscps::forceMotorsStopped();

  Serial.begin(115200);
  delay(100);

  configured =
      configurationValid();

  if (!configured) {
    Serial.println(
        "CONFIGURATION_REQUIRED; "
        "network and motor control disabled"
    );

    return;
  }

  engine.init();

  pinMode(
      LDR_32_PIN,
      INPUT
  );

  pinMode(
      LDR_33_PIN,
      INPUT
  );

  analogReadResolution(12);

  initializeCamera();

  uint8_t randomBoot[16] = {};

  esp_fill_random(
      randomBoot,
      sizeof(randomBoot)
  );

  toHex(
      randomBoot,
      sizeof(randomBoot),
      bootID
  );

  WiFi.mode(WIFI_STA);

  WiFi.setHostname(
      "sentinel-car-01"
  );

  // Use the same controlled reconnect behavior as the
  // previously validated CAR-01 network firmware.
  WiFi.setAutoReconnect(false);

  WiFi.begin(
      SENTINEL_WIFI_SSID,
      SENTINEL_WIFI_PASSWORD
  );

  Serial.println(
      "Sentinel-CPS CAR-01 authenticated firmware"
  );

  Serial.println(
      "Bounded motor diagnostics: 120 ms maximum"
  );

  Serial.println(
      "Physical validation pending"
  );
}


void loop() {
  if (!configured) {
    carscps::forceMotorsStopped();
    delay(10);
    return;
  }

  engine.tick(millis());

  if (
      WiFi.status() !=
      WL_CONNECTED
  ) {
    // Communication loss must always restore the stopped state.
    engine.stop(false);

    if (listening) {
      closePeer();
      server.end();
      listening = false;
    }

    static unsigned long lastReconnectAttempt = 0;
    unsigned long now = millis();

    if (
        now - lastReconnectAttempt >=
        5000
    ) {
      lastReconnectAttempt = now;

      Serial.println(
          "Wi-Fi disconnected; retrying..."
      );

      WiFi.disconnect();
      delay(50);

      WiFi.begin(
          SENTINEL_WIFI_SSID,
          SENTINEL_WIFI_PASSWORD
      );
    }

    delay(10);
    return;
  }

  if (!listening) {
    server.begin();
    listening = true;

    Serial.println(
        "Authenticated CAR service available"
    );
  }

  pollClient();

  engine.tick(millis());

  delay(1);
}
