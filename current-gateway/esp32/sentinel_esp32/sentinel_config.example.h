#pragma once
// Copy to a PRIVATE header outside the release. Never publish a provisioned binary.
// Empty credentials deliberately prevent Wi-Fi startup.
static const char* SENTINEL_WIFI_SSID = "";
static const char* SENTINEL_WIFI_PASSWORD = "";
static const char* SENTINEL_GATEWAY_IP = "";
static const char* SENTINEL_DEVICE_KEY = ""; // 64 lowercase hex; distinct from browser credentials
// Instructor must verify the exact board and LED mapping. -1 means status-only.
static const int SENTINEL_LED_PIN = -1;
static const bool SENTINEL_LED_ACTIVE_HIGH = true;
