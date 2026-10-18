#pragma once
// Copy to a PRIVATE header outside the release. Never publish a provisioned binary.
// Empty credentials deliberately prevent Wi-Fi startup.
static const char* SENTINEL_WIFI_SSID = "";
static const char* SENTINEL_WIFI_PASSWORD = "";
static const char* SENTINEL_GATEWAY_IP = "";
static const char* SENTINEL_DEVICE_KEY = ""; // 64 lowercase hex; distinct from browser credentials
// AI Thinker ESP32-CAM onboard white flash LED; GPIO4 per Espressif CameraWebServer.
// This selects the white LED, not a red indicator. Camera and SD are not initialized.
static const int SENTINEL_LED_PIN = 4;
static const bool SENTINEL_LED_ACTIVE_HIGH = true;
