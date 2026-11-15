// Demo meja SG90 positional, TANPA HORN/PALANG. Bukan pengaman gerbang.
// Isi hanya salinan di luar repo; jangan membagikan konfigurasi asli.
#ifndef WIFI_SSID
#define WIFI_SSID ""
#endif
#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD ""
#endif
#ifndef SERVER_IP
#define SERVER_IP ""
#endif

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <esp_system.h>
#include <esp_arduino_version.h>
#if !defined(CONFIG_IDF_TARGET_ESP32S3)
#error "Pilih board ESP32S3 Dev Module"
#endif
#if ESP_ARDUINO_VERSION_MAJOR < 3
#error "Demo memakai API LEDC esp32 core 3.x"
#endif

static const uint8_t SERVO_PIN = 42;
static const uint16_t ESP_PORT = 5009, LAPTOP_PORT = 5010;
static const uint32_t NONCE_PERIOD_MS = 500, NONCE_TTL_MS = 750;
static const uint32_t WATCHDOG_MS = 2000;
static const uint32_t PWM_FREQ = 50;
static const uint8_t PWM_BITS = 14;
// State: 0 IDLE, 1 ARMED target90, 2 OPENED target110, 3 ERROR, 4 DISARMED.
// Action: 1 ARM, 2 OPEN, 3 DISARM, 4 KEEPALIVE.
static WiFiUDP sUdp;
static IPAddress sServer;
static bool sConfigured = false, sBound = false, sAttached = false;
static uint32_t sBoot = 0, sNonce = 0, sNonceAt = 0, sLastCommand = 0;
static uint32_t sState = 0;

static uint32_t readServo32(const uint8_t* p) {
  return uint32_t(p[0]) | uint32_t(p[1]) << 8 | uint32_t(p[2]) << 16 | uint32_t(p[3]) << 24;
}

static void packServo(uint8_t* out, const char* magic, uint32_t boot, uint32_t nonce, uint32_t value) {
  memcpy(out, magic, 4);
  const uint32_t fields[3] = {boot, nonce, value};
  for (uint8_t field = 0; field < 3; ++field) {
    for (uint8_t byte = 0; byte < 4; ++byte) out[4 + 4 * field + byte] = uint8_t(fields[field] >> (8 * byte));
  }
}

static uint32_t newServoRandom(uint32_t previous) {
  uint32_t value;
  do { value = esp_random(); } while (!value || value == previous);
  return value;
}

static void sendServo(const char* magic) {
  if (!sBound || WiFi.status() != WL_CONNECTED) return;
  uint8_t out[16];
  packServo(out, magic, sBoot, sNonce, sState);
  if (sUdp.beginPacket(sServer, LAPTOP_PORT)) {
    sUdp.write(out, sizeof(out));
    sUdp.endPacket();
  }
}

static void releaseServo(uint32_t state) {
  if (sAttached) { ledcDetach(SERVO_PIN); sAttached = false; }
  pinMode(SERVO_PIN, OUTPUT);
  digitalWrite(SERVO_PIN, LOW);
  sState = state;
  // Detach bukan pemutusan daya, rem atau jaminan posisi mekanik.
}

static bool targetServo(uint16_t degrees) {
  if (!sAttached) {
    if (!ledcAttach(SERVO_PIN, PWM_FREQ, PWM_BITS)) { releaseServo(3); return false; }
    sAttached = true;
  }
  // Rentang pulsa konservatif 1000..2000us; hanya target90/110 dipakai.
  const uint32_t pulseUs = 1000u + uint32_t(degrees) * 1000u / 180u;
  const uint32_t duty = (pulseUs * ((1u << PWM_BITS) - 1u) + 10000u) / 20000u;
  if (!ledcWrite(SERVO_PIN, duty)) { releaseServo(3); return false; }
  return true;
}

static void receiveServo() {
  // Batas kerja per loop; paket panjang dikuras dan tidak diterima sebagian.
  for (uint8_t count = 0; count < 8; ++count) {
    const int size = sUdp.parsePacket();
    if (size <= 0) break;
    const bool peerOk = sUdp.remoteIP() == sServer && sUdp.remotePort() == LAPTOP_PORT;
    uint8_t packet[16];
    const int got = sUdp.read(packet, sizeof(packet));
    sUdp.flush();
    const uint32_t now = millis();
    if (!peerOk || size != 16 || got != 16 || memcmp(packet, "SGC1", 4) != 0) continue;
    if (readServo32(packet + 4) != sBoot || readServo32(packet + 8) != sNonce ||
        uint32_t(now - sNonceAt) > NONCE_TTL_MS) continue;
    // Watchdog juga ditegakkan sebelum paket dapat memperpanjang sesi.
    if ((sState == 1 || sState == 2) && uint32_t(now - sLastCommand) > WATCHDOG_MS) releaseServo(4);
    const uint32_t action = readServo32(packet + 12);
    bool accepted = false;
    if (action == 1 && sState == 0) {
      if (targetServo(90)) { sState = 1; accepted = true; }
    } else if (action == 1 && sState == 1) {
      accepted = true;  // ACK ulang tanpa write/PWM baru.
    } else if (action == 2 && sState == 1) {
      if (targetServo(110)) { sState = 2; accepted = true; }
    } else if (action == 2 && sState == 2) {
      accepted = true;  // OPEN duplikat tidak mengulangi gerak.
    } else if (action == 3) {
      if (sState != 3 && sState != 4) releaseServo(4);
      accepted = true;
    } else if (action == 4 && (sState == 1 || sState == 2)) {
      accepted = true;
    }
    if (accepted) sLastCommand = now;
    // ACK mencerminkan target/state saja; bukan pengukuran posisi fisik.
    if (accepted || sState == 3 || sState == 4) sendServo("SGK1");
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(SERVO_PIN, OUTPUT);
  digitalWrite(SERVO_PIN, LOW);
  Serial.println("[SERVO] IDLE tanpa PWM; ARM eksplisit akan menargetkan90. Lepas horn/palang.");
  sConfigured = strlen(WIFI_SSID) > 0 && sServer.fromString(SERVER_IP) &&
                sServer[0] > 0 && sServer[0] != 127 && sServer[0] < 224 && sServer[3] != 255;
  if (!sConfigured) {
    Serial.println("[CONFIG] Isi WIFI_SSID/WIFI_PASSWORD/SERVER_IP pada salinan privat. Tidak ada koneksi/gerak.");
    return;
  }
  sBoot = newServoRandom(0);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

void loop() {
  if (!sConfigured) { delay(2); return; }
  uint32_t now = millis();
  if ((sState == 1 || sState == 2) &&
      (WiFi.status() != WL_CONNECTED || uint32_t(now - sLastCommand) > WATCHDOG_MS)) {
    releaseServo(4);  // Tidak pernah mengirim target tutup otomatis.
  }
  if (WiFi.status() != WL_CONNECTED) {
    if (sBound) { sUdp.stop(); sBound = false; }
    delay(2);
    return;
  }
  if (!sBound) {
    if (!sUdp.begin(ESP_PORT)) { delay(2); return; }
    sBound = true;
    Serial.printf("[WIFI] IP ESP: %s | UDP5009 -> laptop5010\n", WiFi.localIP().toString().c_str());
    sNonce = newServoRandom(sNonce);
    sNonceAt = now;
    sendServo("SGH1");
  } else if (uint32_t(now - sNonceAt) >= NONCE_PERIOD_MS) {
    sNonce = newServoRandom(sNonce);
    sNonceAt = now;
    sendServo("SGH1");
  }
  receiveServo();
  delay(2);
}
