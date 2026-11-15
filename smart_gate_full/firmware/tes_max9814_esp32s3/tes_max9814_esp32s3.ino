/*
 * Tes MAX9814 saja - ESP32-S3 / Arduino IDE.
 * VDD -> 3V3, GND -> GND, OUT -> GPIO1 (BUKAN RX/GPIO44).
 * Tidak menggunakan HC-SR04, servo, LCD, Wi-Fi atau ML.
 * Serial Monitor: 115200 baud. Statistik ADC, bukan dB/deteksi sirene.
 */
#include <Arduino.h>
#include <esp_arduino_version.h>

#if !defined(CONFIG_IDF_TARGET_ESP32S3)
#error "Pilih board ESP32S3 Dev Module."
#endif
#if ESP_ARDUINO_VERSION_MAJOR < 3
#error "Gunakan paket esp32 by Espressif Systems versi 3.x."
#endif

constexpr uint8_t MIC_PIN = 1;
constexpr uint32_t SAMPLE_INTERVAL_US = 250;
constexpr uint32_t REPORT_INTERVAL_MS = 250;
uint32_t lastSampleUs = 0;
uint32_t lastReportMs = 0;
uint16_t micMin = 4095;
uint16_t micMax = 0;
uint16_t micRaw = 0;
uint32_t micSum = 0;
uint32_t micCount = 0;
bool clipped = false;

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);
  analogSetPinAttenuation(MIC_PIN, ADC_11db);
}

void loop() {
  const uint32_t nowUs = micros();
  if (static_cast<uint32_t>(nowUs - lastSampleUs) >= SAMPLE_INTERVAL_US) {
    lastSampleUs = nowUs;  // Best effort, bukan audio uniform 16 kHz.
    micRaw = analogRead(MIC_PIN);
    if (micRaw < micMin) micMin = micRaw;
    if (micRaw > micMax) micMax = micRaw;
    micSum += micRaw;
    ++micCount;
    if (micRaw <= 10 || micRaw >= 4085) clipped = true;
  }

  const uint32_t nowMs = millis();
  if (static_cast<uint32_t>(nowMs - lastReportMs) >= REPORT_INTERVAL_MS && micCount) {
    lastReportMs = nowMs;
    Serial.print("RAW="); Serial.print(micRaw);
    Serial.print(" MIN="); Serial.print(micMin);
    Serial.print(" MAX="); Serial.print(micMax);
    Serial.print(" P2P="); Serial.print(micMax - micMin);
    Serial.print(" AVG="); Serial.print(micSum / micCount);
    Serial.print(" N="); Serial.print(micCount);
    Serial.print(" CLIP="); Serial.println(clipped ? "YES" : "NO");
    micMin = 4095;
    micMax = 0;
    micSum = 0;
    micCount = 0;
    clipped = false;
  }
}
