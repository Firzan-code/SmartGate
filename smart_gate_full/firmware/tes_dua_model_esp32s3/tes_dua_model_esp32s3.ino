/*
 * TES DUA MODEL - ESP32-S3 + MAX9814 (satu file untuk tugas kuliah)
 * Isi tiga nilai di bawah. Model wajah/mata dan sirene berjalan di laptop.
 * MAX9814: VDD=3V3, GND=GND, OUT=GPIO1. Serial Monitor=115200.
 * Jangan bagikan file/screenshot yang masih berisi password Wi-Fi asli.
 */
#ifndef WIFI_SSID
#define WIFI_SSID ""
#endif
#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD ""
#endif
#ifndef SERVER_IP
#define SERVER_IP ""
#endif
// SERVER_IP: IPv4 laptop dari terminal dashboard, tanpa http:// atau port.
// USB native: ESP32S3 Dev Module; USB CDC On Boot Enabled; Hardware CDC and JTAG.
// Selanjutnya tidak perlu diubah untuk uji biasa.

// ---------- Format audio dan ringkasan laptop ----------

#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace dual {
constexpr uint32_t kSampleRate = 16000;
constexpr size_t kSampleCount = 320;
constexpr size_t kHeaderBytes = 20;
constexpr size_t kPacketBytes = kHeaderBytes + 2 * kSampleCount;
constexpr uint16_t kDiscontinuity = 1;

// Serialize explicitly: neither compiler padding nor host byte order is on wire.
struct AudioPacket {
  uint8_t bytes[kPacketBytes] = {};
};
static_assert(sizeof(AudioPacket) == 660, "SGA1 packet must be 660 bytes");

inline void put16(uint8_t *out, uint16_t value) {
  out[0] = static_cast<uint8_t>(value);
  out[1] = static_cast<uint8_t>(value >> 8);
}
inline void put32(uint8_t *out, uint32_t value) {
  put16(out, static_cast<uint16_t>(value));
  put16(out + 2, static_cast<uint16_t>(value >> 16));
}

class Packetizer {
 public:
  explicit Packetizer(uint32_t boot_id, uint32_t first_sequence = 0)
      : boot_id_(boot_id), sequence_(first_sequence) {}

  void markDiscontinuity() { count_ = 0; discontinuity_ = true; }

  template <typename Sink>
  void push(unsigned unit, unsigned channel, unsigned raw, Sink sink) {
    // ESP32-S3 TYPE2 unit 0 denotes ADC1 (not the number 1).
    if (unit != 0 || channel != 0 || raw > 4095) {
      markDiscontinuity();
      return;
    }
    put16(packet_.bytes + kHeaderBytes + 2 * count_, static_cast<uint16_t>(raw));
    if (++count_ != kSampleCount) return;
    packet_.bytes[0] = 'S'; packet_.bytes[1] = 'G';
    packet_.bytes[2] = 'A'; packet_.bytes[3] = '1';
    put32(packet_.bytes + 4, boot_id_);
    put32(packet_.bytes + 8, sequence_++);
    put32(packet_.bytes + 12, kSampleRate);
    put16(packet_.bytes + 16, kSampleCount);
    put16(packet_.bytes + 18, discontinuity_ ? kDiscontinuity : 0);
    discontinuity_ = !sink(packet_);
    count_ = 0;
  }

 private:
  AudioPacket packet_;
  uint32_t boot_id_;
  uint32_t sequence_ = 0;
  size_t count_ = 0;
  bool discontinuity_ = true;
};
class ReplyClock {
 public:
  void accept(uint32_t now) { last_ = now; seen_ = true; }
  void clear() { seen_ = false; }
  bool stale(uint32_t now) const { return !seen_ || static_cast<uint32_t>(now - last_) > 3000; }
 private:
  uint32_t last_ = 0;
  bool seen_ = false;
};

inline bool parseReply(const uint8_t *bytes, size_t length, char *out, size_t capacity) {
  if (!bytes || !out || length < 6 || length > 512 || length >= capacity ||
      memcmp(bytes, "SGR1 ", 5) != 0) return false;
  bool content = false;
  for (size_t i = 5; i < length; ++i) {
    if (bytes[i] < 32 || bytes[i] > 126) return false;
    content = content || bytes[i] != ' ';
  }
  if (!content) return false;
  memcpy(out, bytes, length);
  out[length] = '\0';
  return true;
}
}  // namespace dual

#ifndef DUAL_PROTOCOL_ONLY
// ---------- Akuisisi mikrofon, Wi-Fi, dan Serial ----------
#include <Arduino.h>
#include <WiFi.h>
#include <lwip/sockets.h>
#include <lwip/inet.h>
#include <fcntl.h>
#include <errno.h>
#include <esp_random.h>
#include <esp_adc/adc_continuous.h>
#include <soc/soc_caps.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>
#if !defined(CONFIG_IDF_TARGET_ESP32S3)
#error "Sketch ini hanya untuk ESP32-S3"
#endif
static_assert(dual::kSampleRate >= SOC_ADC_SAMPLE_FREQ_THRES_LOW &&
              dual::kSampleRate <= SOC_ADC_SAMPLE_FREQ_THRES_HIGH, "ADC rate unsupported");
static_assert(SOC_ADC_DIGI_RESULT_BYTES == sizeof(adc_digi_output_data_t), "TYPE2 size");
namespace dual_fw {
constexpr uint32_t kFrameBytes = dual::kSampleCount * SOC_ADC_DIGI_RESULT_BYTES;
constexpr unsigned kQueuePackets = 6;
struct QueuedAudio { dual::AudioPacket packet; uint32_t capturedAt; uint32_t epoch; };
inline QueueHandle_t audioQueue = nullptr;
inline TaskHandle_t acquisitionHandle = nullptr;
inline adc_continuous_handle_t adc = nullptr;
inline bool adcRunning = false, active = false, configMissing = false;
inline uint32_t lastConfig = 0;
inline portMUX_TYPE stateMux = portMUX_INITIALIZER_UNLOCKED;
struct Shared { bool fatal = false; bool overflow = false; bool linkLost = false; bool adcReady = false; uint32_t epoch = 0;
  const char *error = nullptr; esp_err_t code = ESP_OK; };
inline Shared shared;
inline dual::Packetizer packetizer(0);
inline char serialOut[600] = {};
inline size_t serialLength = 0, serialOffset = 0;
inline bool serialIsSummary = false;
inline uint32_t summaryQueuedAt = 0, summaryEpoch = 0;
inline dual::ReplyClock replyClock;
inline uint32_t networkEpoch = 0;
inline void message(const char *text) {
  serialIsSummary = false;
  serialLength = strlen(text);
  if (serialLength > sizeof(serialOut) - 2) serialLength = sizeof(serialOut) - 2;
  memcpy(serialOut, text, serialLength);
  serialOut[serialLength++] = '\n'; serialOffset = 0;
}
inline bool diagnosticShown = false;
inline uint32_t lastDiagnostic = 0;
inline void diagnostic(const char *text) {
  if (diagnosticShown && static_cast<uint32_t>(millis() - lastDiagnostic) < 1000) return;
  diagnosticShown = true; lastDiagnostic = millis(); message(text);
}
inline void pumpSerial() {
  const int space = Serial.availableForWrite();
  const uint32_t now = millis();
  uint8_t chunk[64]; size_t n = 0;
  portENTER_CRITICAL(&stateMux);
  if (serialIsSummary) {
    // Validate after availableForWrite: it can stall while the source changes.
    const bool invalid = shared.fatal || shared.overflow || shared.linkLost ||
      shared.epoch != summaryEpoch || networkEpoch != summaryEpoch;
    const bool expired = static_cast<uint32_t>(now - summaryQueuedAt) > 3000;
    if (invalid || expired) {
      replyClock.clear();
      message("BASI/MENUNGGU: hasil kedaluwarsa sebelum Serial siap");
    }
  }
  if (space > 0 && serialOffset < serialLength) {
    n = serialLength - serialOffset;
    if (n > sizeof(chunk)) n = sizeof(chunk);
    if (n > static_cast<size_t>(space)) n = static_cast<size_t>(space);
    memcpy(chunk, serialOut + serialOffset, n);
  }
  // Commit one ready chunk against source invalidation. A later event cancels
  // subsequent chunks, not bytes already committed; never hold the ADC lock in I/O.
  portEXIT_CRITICAL(&stateMux);
  if (n) serialOffset += Serial.write(chunk, n);
}
inline void fail(const char *what, esp_err_t code) {
  portENTER_CRITICAL(&stateMux);
  shared.fatal = true; shared.error = what; shared.code = code;
  portEXIT_CRITICAL(&stateMux);
}
static bool IRAM_ATTR onOverflow(adc_continuous_handle_t, const adc_continuous_evt_data_t *, void *) {
  portENTER_CRITICAL_ISR(&stateMux); shared.overflow = true; portEXIT_CRITICAL_ISR(&stateMux);
  return false;
}
inline bool ipv4(uint32_t &address) {
  const char *p = SERVER_IP; uint32_t value = 0;
  for (unsigned octet = 0; octet < 4; ++octet) {
    unsigned n = 0, digits = 0;
    while (*p >= '0' && *p <= '9') { n = n * 10 + static_cast<unsigned>(*p++ - '0'); if (++digits > 3 || n > 255) return false; }
    if (!digits || (octet < 3 ? *p++ != '.' : *p != '\0')) return false;
    value = (value << 8) | n;
  }
  if (!value || (value >> 24) >= 224 || (value >> 24) == 0 || value == UINT32_MAX) return false;
  address = value; return true;
}
inline uint32_t serverAddress = 0;
inline Shared snapshot() {
  portENTER_CRITICAL(&stateMux); const Shared s = shared; portEXIT_CRITICAL(&stateMux); return s;
}
inline uint32_t lastAcquisition = 0, packetStart = 0, acquisitionEpoch = 0;
inline unsigned partialSamples = 0;
inline bool recoverAdc() {
  partialSamples = 0;
  lastAcquisition = millis();
  packetizer.markDiscontinuity();
  portENTER_CRITICAL(&stateMux); ++shared.epoch; acquisitionEpoch = shared.epoch; shared.overflow = false; portEXIT_CRITICAL(&stateMux);
  if (xQueueReset(audioQueue) != pdPASS) { fail("queue reset", ESP_FAIL); return false; }
  esp_err_t e = adc_continuous_stop(adc);
  if (e != ESP_OK) { fail("ADC recovery stop", e); return false; }
  adcRunning = false;
  e = adc_continuous_flush_pool(adc);
  if (e != ESP_OK) { fail("ADC recovery flush", e); return false; }
  e = adc_continuous_start(adc);
  if (e != ESP_OK) { fail("ADC recovery start", e); return false; }
  adcRunning = true;
  return true;
}
inline bool initAdc();
inline void cleanupStartup();
inline bool acquisitionStopped = false, acquisitionInitialized = false;
inline void acquisitionStep() {
  // Only acquisitionTask enters this state machine. IDF start/stop own a task mutex.
  if (!acquisitionInitialized) {
    acquisitionInitialized = true;
    if (!initAdc()) { cleanupStartup(); acquisitionStopped = true; return; }
    portENTER_CRITICAL(&stateMux); shared.adcReady = true; portEXIT_CRITICAL(&stateMux);
    return;
  }
  if (snapshot().fatal) {
    if (!acquisitionStopped) {
      acquisitionStopped = true;
      if (adcRunning) {
        const esp_err_t e = adc_continuous_stop(adc);
        if (e != ESP_OK) fail("ADC fatal stop", e);
        adcRunning = false;
      }
      if (xQueueReset(audioQueue) != pdPASS) fail("queue reset", ESP_FAIL);
    }
    return;
  }
  if (snapshot().overflow || snapshot().epoch != acquisitionEpoch ||
      static_cast<uint32_t>(millis() - lastAcquisition) > 40) {
    recoverAdc(); return;
  }
  lastAcquisition = millis();
  alignas(adc_digi_output_data_t) uint8_t raw[kFrameBytes];
  uint32_t length = 0;
  const esp_err_t e = adc_continuous_read(adc, raw, sizeof(raw), &length, 30);
  if (snapshot().overflow || static_cast<uint32_t>(millis() - lastAcquisition) > 40) {
    recoverAdc(); return;
  }
  if (e == ESP_ERR_TIMEOUT || e == ESP_ERR_INVALID_STATE) { recoverAdc(); return; }
  if (e != ESP_OK) { fail("ADC read", e); return; }
  if (length == 0 || length > sizeof(raw) || length % SOC_ADC_DIGI_RESULT_BYTES != 0) {
    recoverAdc(); return;
  }
  for (uint32_t i = 0; i + SOC_ADC_DIGI_RESULT_BYTES <= length; i += SOC_ADC_DIGI_RESULT_BYTES) {
    adc_digi_output_data_t value{}; memcpy(&value, raw + i, sizeof(value));
    if (value.type2.unit != 0 || value.type2.channel != 0 || value.type2.data > 4095) partialSamples = 0;
    else {
      if (partialSamples == 0) packetStart = lastAcquisition - 60; // read-start minus DMA/pool upper bound, never parse time
      partialSamples = (partialSamples + 1) % dual::kSampleCount;
    }
    packetizer.push(value.type2.unit, value.type2.channel, value.type2.data,
      [](const dual::AudioPacket &p) {
        const Shared s = snapshot();
        if (s.fatal || s.overflow || s.epoch != acquisitionEpoch) return false;
        QueuedAudio q{p, packetStart, acquisitionEpoch};
        return xQueueSend(audioQueue, &q, 0) == pdTRUE;
      });
  }
}
inline void acquisitionTask(void *) { for (;;) { acquisitionStep(); vTaskDelay(pdMS_TO_TICKS(1)); } }
inline void cleanupStartup() {
  if (adcRunning) {
    const esp_err_t e = adc_continuous_stop(adc);
    if (e != ESP_OK) { fail("ADC stop", e); return; }
    adcRunning = false;
  }
  if (adc) {
    const esp_err_t e = adc_continuous_deinit(adc);
    if (e != ESP_OK) fail("ADC deinit", e);
    else adc = nullptr;
  }
  if (audioQueue) { vQueueDelete(audioQueue); audioQueue = nullptr; }
}
inline bool initAdc() {
  adc_unit_t unit; adc_channel_t channel;
  esp_err_t e = adc_continuous_io_to_channel(1, &unit, &channel);
  if (e != ESP_OK || unit != ADC_UNIT_1 || channel != ADC_CHANNEL_0) { fail("GPIO1 ADC1_CH0", e); return false; }
  audioQueue = xQueueCreate(kQueuePackets, sizeof(QueuedAudio));
  if (!audioQueue) { fail("queue allocation", ESP_FAIL); return false; }
  adc_continuous_handle_cfg_t handle{};
  handle.max_store_buf_size = 2 * kFrameBytes; handle.conv_frame_size = kFrameBytes;
  e = adc_continuous_new_handle(&handle, &adc);
  if (e != ESP_OK) { fail("ADC handle", e); return false; }
  adc_digi_pattern_config_t pattern{};
  pattern.atten = ADC_ATTEN_DB_12; pattern.channel = ADC_CHANNEL_0;
  pattern.unit = ADC_UNIT_1; pattern.bit_width = ADC_BITWIDTH_12;
  adc_continuous_config_t config{};
  config.sample_freq_hz = dual::kSampleRate; config.conv_mode = ADC_CONV_SINGLE_UNIT_1;
  config.format = ADC_DIGI_OUTPUT_FORMAT_TYPE2; config.pattern_num = 1; config.adc_pattern = &pattern;
  e = adc_continuous_config(adc, &config);
  if (e != ESP_OK) { fail("ADC config", e); return false; }
  adc_continuous_evt_cbs_t callbacks{}; callbacks.on_pool_ovf = onOverflow;
  e = adc_continuous_register_event_callbacks(adc, &callbacks, nullptr);
  if (e != ESP_OK) { fail("ADC callback", e); return false; }
  e = adc_continuous_start(adc);
  if (e != ESP_OK) { fail("ADC start", e); return false; }
  adcRunning = true; lastAcquisition = millis();
  return true;
}
inline void setupFirmware() {
  Serial.begin(115200);
  if (!WIFI_SSID[0] || !ipv4(serverAddress)) {
    configMissing = true; lastConfig = millis();
    message("CONFIG: isi WIFI_SSID/WIFI_PASSWORD/SERVER_IP di bagian atas sketch"); pumpSerial(); return;
  }
  packetizer = dual::Packetizer(esp_random());
  // setup/loopTask must never start or stop ADC: acquisitionTask owns its lifecycle.
  if (xTaskCreatePinnedToCore(acquisitionTask, "max9814-dma", 4096, nullptr, 3, &acquisitionHandle, 1) != pdPASS) {
    fail("acquisition task", ESP_FAIL);
    message("ERROR acquisition task; audio tidak aktif"); pumpSerial(); return;
  }
  message("ADC DMA: menunggu task akuisisi"); pumpSerial();
}
inline int udp = -1;
inline sockaddr_in server{};
inline bool openUdp() {
  udp = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
  if (udp < 0) { message("ERROR UDP socket / MENUNGGU"); return false; }
  const int flags = fcntl(udp, F_GETFL, 0);
  sockaddr_in local{}; local.sin_family = AF_INET;
  local.sin_port = htons(5007); local.sin_addr.s_addr = htonl(INADDR_ANY);
  if (flags < 0 || fcntl(udp, F_SETFL, flags | O_NONBLOCK) < 0 ||
      bind(udp, reinterpret_cast<const sockaddr *>(&local), sizeof(local)) < 0) {
    if (close(udp) < 0) fail("UDP close", ESP_FAIL);
    udp = -1; message("ERROR UDP nonblock/bind / MENUNGGU"); return false;
  }
  server.sin_family = AF_INET; server.sin_port = htons(5006);
  server.sin_addr.s_addr = htonl(serverAddress);
  return true;
}
inline bool txDiscontinuity = true, sendErrorShown = false;
inline uint32_t lastSendError = 0;
inline void sendAudio() {
  QueuedAudio q{};
  if (xQueueReceive(audioQueue, &q, 0) != pdTRUE) return;
  const Shared state = snapshot();
  if (state.fatal || state.overflow || q.epoch != state.epoch ||
      static_cast<uint32_t>(millis() - q.capturedAt) > 150) {
    txDiscontinuity = true; return;
  }
  if (txDiscontinuity) dual::put16(q.packet.bytes + 18, dual::kDiscontinuity);
  const int sent = sendto(udp, q.packet.bytes, sizeof(q.packet.bytes), MSG_DONTWAIT,
                          reinterpret_cast<const sockaddr *>(&server), sizeof(server));
  txDiscontinuity = sent != static_cast<int>(sizeof(q.packet.bytes));
  if (txDiscontinuity && (!sendErrorShown || static_cast<uint32_t>(millis() - lastSendError) >= 1000)) {
    sendErrorShown = true; lastSendError = millis(); message("ERROR UDP send / audio terputus");
  }
}
inline void resetStream() {
  portENTER_CRITICAL(&stateMux); ++shared.epoch; portEXIT_CRITICAL(&stateMux);
  if (xQueueReset(audioQueue) != pdPASS) fail("queue reset", ESP_FAIL);
}
inline void closeUdp() {
  if (udp >= 0 && close(udp) < 0) fail("UDP close", ESP_FAIL);
  udp = -1;
}
inline bool staleWarning = false;
inline uint32_t lastStaleWarning = 0, lastSummary = 0;
inline bool summaryPrinted = false;
inline void receiveReplies() {
  const Shared source = snapshot();
  if (source.fatal || source.overflow || source.linkLost || source.epoch != networkEpoch) {
    replyClock.clear(); return;
  }
  uint8_t bytes[513]; sockaddr_in peer{}; socklen_t size = sizeof(peer);
  const int n = recvfrom(udp, bytes, sizeof(bytes), MSG_DONTWAIT,
                         reinterpret_cast<sockaddr *>(&peer), &size);
  if (n < 0) {
    if (errno != EWOULDBLOCK && errno != EAGAIN) {
      replyClock.clear(); closeUdp(); txDiscontinuity = true;
      message("ERROR UDP read / BASI/MENUNGGU");
    }
    return;
  }
  if (n == 0) return;
  char text[513];
  if (size == sizeof(peer) && peer.sin_family == AF_INET && peer.sin_port == server.sin_port &&
      peer.sin_addr.s_addr == server.sin_addr.s_addr && dual::parseReply(bytes, static_cast<size_t>(n), text, sizeof(text))) {
    // recvfrom/parse run without the ADC lock; commit only to the same live source.
    const uint32_t now = millis();
    portENTER_CRITICAL(&stateMux);
    if (shared.fatal || shared.overflow || shared.linkLost || shared.epoch != source.epoch ||
        source.epoch != networkEpoch) {
      replyClock.clear(); portEXIT_CRITICAL(&stateMux); return;
    }
    replyClock.accept(now); staleWarning = false;
    if (!summaryPrinted || static_cast<uint32_t>(now - lastSummary) >= 250) {
      summaryPrinted = true; lastSummary = now; message(text);
      serialIsSummary = true; summaryQueuedAt = now; summaryEpoch = source.epoch;
    }
    portEXIT_CRITICAL(&stateMux);
  }
}
inline void onWifiEvent(arduino_event_id_t) {
  portENTER_CRITICAL(&stateMux);
  shared.linkLost = true; ++shared.epoch;
  portEXIT_CRITICAL(&stateMux);
}
inline bool wifiReady = false, triedWifi = false, connected = false;
inline uint32_t lastWifiAttempt = 0, lastSocketAttempt = 0;
inline bool triedSocket = false;
inline void networkStep() {
  if (!wifiReady) {
    WiFi.persistent(false);
    if (!WiFi.mode(WIFI_STA) || !WiFi.setSleep(false) || !WiFi.setAutoReconnect(false) ||
        !WiFi.onEvent(onWifiEvent, ARDUINO_EVENT_WIFI_STA_DISCONNECTED)) { fail("WiFi station/sleep", ESP_FAIL); return; }
    wifiReady = true;
  }
  if (WiFi.status() != WL_CONNECTED &&
      (!triedWifi || static_cast<uint32_t>(millis() - lastWifiAttempt) >= 5000)) {
    triedWifi = true; lastWifiAttempt = millis();
    if (WiFi.begin(WIFI_SSID, WIFI_PASSWORD) == WL_CONNECT_FAILED)
      message("WiFi gagal; retry 5 detik / MENUNGGU");
  }
  const bool online = WiFi.status() == WL_CONNECTED;
  portENTER_CRITICAL(&stateMux); const bool linkLost = shared.linkLost; shared.linkLost = false; portEXIT_CRITICAL(&stateMux);
  if (online != connected || linkLost) {
    connected = online; txDiscontinuity = true; resetStream(); closeUdp();
    replyClock.clear(); triedSocket = false;
    serialLength = serialOffset = 0;
    diagnostic("BASI/MENUNGGU: koneksi berubah; audio lama dibuang");
  }
  if (online) {
    if (udp < 0) {
      if (triedSocket && static_cast<uint32_t>(millis() - lastSocketAttempt) < 5000) return;
      triedSocket = true; lastSocketAttempt = millis();
      if (!openUdp()) return;
      resetStream(); txDiscontinuity = true; replyClock.clear();
      return;
    }
    const uint32_t epoch = snapshot().epoch;
    if (epoch != networkEpoch) {
      networkEpoch = epoch; replyClock.clear(); txDiscontinuity = true;
      serialLength = serialOffset = 0;
      diagnostic("BASI/MENUNGGU: celah akuisisi; hasil lama dibuang");
      closeUdp(); triedSocket = true; lastSocketAttempt = millis();
      if (!openUdp()) return;
    }
    sendAudio();
    receiveReplies();
  }
}
inline bool fatalReported = false;
inline void loopFirmware() {
  const Shared startup = snapshot();
  if (!active && startup.adcReady && !startup.fatal) {
    active = true;
    message("ADC DMA: rate dikonfigurasi=16000 Hz; belum terukur");
  }
  if (configMissing && static_cast<uint32_t>(millis() - lastConfig) >= 3000) {
    lastConfig = millis(); message("CONFIG: isi WIFI_SSID/WIFI_PASSWORD/SERVER_IP di bagian atas sketch");
  }
  if (active && !snapshot().fatal) {
    networkStep();
    if (replyClock.stale(millis()) && (!staleWarning ||
        static_cast<uint32_t>(millis() - lastStaleWarning) >= 3000)) {
      staleWarning = true; lastStaleWarning = millis();
      message("BASI/MENUNGGU: belum ada hasil valid <=3 detik");
    }
  }
  if (snapshot().fatal && !fatalReported) {
    fatalReported = true; closeUdp(); replyClock.clear();
    char text[160]; const Shared s = snapshot();
    snprintf(text, sizeof(text), "ERROR %s code=%d; audio tidak aktif", s.error ? s.error : "firmware", static_cast<int>(s.code));
    message(text);
  }
  pumpSerial(); delay(5);
}
}  // namespace dual_fw

void setup() { dual_fw::setupFirmware(); }
void loop() { dual_fw::loopFirmware(); }
#endif  // DUAL_PROTOCOL_ONLY
