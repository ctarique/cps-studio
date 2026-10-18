#pragma once

// Public template only.
// Copy to sentinel_car_config.local.h for provisioning.
// Never publish the provisioned header or binary.

static const char* SENTINEL_WIFI_SSID = "";
static const char* SENTINEL_WIFI_PASSWORD = "";
static const char* SENTINEL_GATEWAY_IP = "";

// 64 lowercase hexadecimal characters.
// This CAR-01 credential must be distinct from CAM-01 and browser/admin
// credentials.
static const char* SENTINEL_CAR_DEVICE_KEY = "";
