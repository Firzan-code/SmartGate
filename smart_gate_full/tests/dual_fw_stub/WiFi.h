#pragma once
#include "Arduino.h"
constexpr int WIFI_STA = 1, WL_CONNECTED = 3, WL_DISCONNECTED = 6, WL_CONNECT_FAILED = 4;
using arduino_event_id_t = int;
using network_event_handle_t = size_t;
constexpr int ARDUINO_EVENT_WIFI_STA_DISCONNECTED = 57;
namespace fake {
inline int wifiStatus = WL_DISCONNECTED; inline int wifiBegins = 0;
inline bool persistent = true, autoReconnect = true;
inline void (*wifiEvent)(arduino_event_id_t) = nullptr;
}
struct FakeWiFi {
 void persistent(bool v) { fake::persistent = v; }
 bool setAutoReconnect(bool v) { fake::autoReconnect = v; return fake::ok(); }
 network_event_handle_t onEvent(void (*cb)(arduino_event_id_t), int) { fake::wifiEvent=cb; return fake::ok() ? 1 : 0; }
 bool mode(int) { ++fake::wifiCalls; return fake::ok(); }
 bool setSleep(bool value) { ++fake::wifiCalls; return !value && fake::ok(); }
 int begin(const char *, const char *) { ++fake::wifiBegins; ++fake::wifiCalls; return fake::ok() ? fake::wifiStatus : WL_CONNECT_FAILED; }
 int status() { return fake::wifiStatus; }
 bool disconnect(bool = false, bool = false) { ++fake::wifiCalls; return fake::ok(); }
};
inline FakeWiFi WiFi;
