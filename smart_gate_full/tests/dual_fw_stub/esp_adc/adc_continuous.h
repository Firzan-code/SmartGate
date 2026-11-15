#pragma once
#include "Arduino.h"
#include "freertos/task.h"
#include <cstdlib>
using esp_err_t = int;
constexpr int ESP_OK = 0, ESP_FAIL = -1, ESP_ERR_TIMEOUT = 1, ESP_ERR_INVALID_STATE = 2;
using adc_unit_t = int;
using adc_channel_t = int;
constexpr int ADC_UNIT_1 = 0, ADC_CHANNEL_0 = 0, ADC_BITWIDTH_12 = 12, ADC_ATTEN_DB_12 = 3;
constexpr int ADC_CONV_SINGLE_UNIT_1 = 1, ADC_DIGI_OUTPUT_FORMAT_TYPE2 = 2;
union adc_digi_output_data_t {
 struct { uint32_t data:12; uint32_t reserved12:1; uint32_t channel:4; uint32_t unit:1; uint32_t reserved17_31:14; } type2;
 uint32_t val;
};
using adc_continuous_handle_t = void *;
struct adc_digi_pattern_config_t { uint8_t atten, channel, unit, bit_width; };
struct adc_continuous_handle_cfg_t { uint32_t max_store_buf_size, conv_frame_size; struct { uint32_t flush_pool:1; } flags; };
struct adc_continuous_config_t { uint32_t pattern_num; adc_digi_pattern_config_t *adc_pattern; uint32_t sample_freq_hz; int conv_mode, format; };
struct adc_continuous_evt_data_t { uint8_t *conv_frame_buffer; uint32_t size; };
using adc_continuous_callback_t = bool (*)(adc_continuous_handle_t, const adc_continuous_evt_data_t *, void *);
struct adc_continuous_evt_cbs_t { adc_continuous_callback_t on_conv_done, on_pool_ovf; };
namespace fake {
inline adc_continuous_handle_cfg_t adcHandleConfig{};
inline adc_continuous_config_t adcConfig{};
inline adc_digi_pattern_config_t adcPattern{};
inline adc_continuous_evt_cbs_t callbacks{};
inline int starts = 0, stops = 0, flushes = 0, deinits = 0;
inline int mappedGpio = -1;
inline bool badMapping = false;
inline std::deque<std::vector<uint8_t>> dma;
inline int readError = ESP_OK;
inline uint32_t readAdvance = 0, readTimeout = 0;
inline bool overflowDuringRead = false;
inline std::vector<std::string> lifecycle;
inline uintptr_t adcOwner = 0, adcCreator = 0;
inline bool adcStarted = false;
inline bool enforceOwner = true;
inline std::vector<uintptr_t> lifecycleTasks;
inline void requireAdcCreator() {
 if (enforceOwner && adcCreator != currentTask) {
   std::fprintf(stderr, "ASSERT ADC lifecycle creator=%zu current_task=%zu\n",
                static_cast<size_t>(adcCreator), static_cast<size_t>(currentTask));
   std::abort();
 }
}
inline void requireAdcOwner() {
 if (enforceOwner && (!adcStarted || adcOwner != currentTask)) {
   std::fprintf(stderr, "ASSERT ADC mutex owner=%zu current_task=%zu (xTaskPriorityDisinherit)\n",
                static_cast<size_t>(adcOwner), static_cast<size_t>(currentTask));
   std::abort();
 }
}
inline void frame(unsigned n = 320, unsigned unit = 0, unsigned ch = 0, unsigned raw = 42) {
 std::vector<uint8_t> v(n * 4);
 for (unsigned i = 0; i < n; ++i) { adc_digi_output_data_t d{}; d.type2.unit=unit; d.type2.channel=ch; d.type2.data=raw; std::memcpy(v.data()+i*4,&d,4); }
 dma.push_back(v);
}
}
inline esp_err_t adc_continuous_io_to_channel(int gpio, adc_unit_t *u, adc_channel_t *c) { ++fake::adcCalls; fake::mappedGpio=gpio; *u=fake::badMapping?1:0; *c=0; return fake::ok()?ESP_OK:ESP_FAIL; }
inline esp_err_t adc_continuous_new_handle(const adc_continuous_handle_cfg_t *cfg, adc_continuous_handle_t *h) { ++fake::adcCalls; fake::adcHandleConfig=*cfg; if (!fake::ok()) return ESP_FAIL; *h=reinterpret_cast<void *>(1); fake::adcCreator=fake::currentTask; return ESP_OK; }
inline esp_err_t adc_continuous_config(adc_continuous_handle_t, const adc_continuous_config_t *c) { ++fake::adcCalls; fake::adcConfig=*c; fake::adcPattern=*c->adc_pattern; return fake::ok()?ESP_OK:ESP_FAIL; }
inline esp_err_t adc_continuous_register_event_callbacks(adc_continuous_handle_t, const adc_continuous_evt_cbs_t *c, void *) { ++fake::adcCalls; fake::callbacks=*c; return fake::ok()?ESP_OK:ESP_FAIL; }
inline esp_err_t adc_continuous_start(adc_continuous_handle_t) {
 fake::requireAdcCreator();
 ++fake::adcCalls; ++fake::starts; fake::lifecycle.push_back("start");
 fake::lifecycleTasks.push_back(fake::currentTask);
 if (!fake::ok()) return ESP_FAIL;
 fake::adcOwner=fake::currentTask; fake::adcStarted=true; return ESP_OK;
}
inline esp_err_t adc_continuous_stop(adc_continuous_handle_t) {
 fake::requireAdcOwner();
 ++fake::adcCalls; ++fake::stops; fake::lifecycle.push_back("stop");
 fake::lifecycleTasks.push_back(fake::currentTask);
 if (!fake::ok()) return ESP_FAIL;
 fake::adcOwner=0; fake::adcStarted=false; return ESP_OK;
}
inline esp_err_t adc_continuous_flush_pool(adc_continuous_handle_t) { fake::requireAdcCreator(); ++fake::adcCalls; ++fake::flushes; fake::lifecycle.push_back("flush"); fake::dma.clear(); return fake::ok()?ESP_OK:ESP_FAIL; }
inline esp_err_t adc_continuous_deinit(adc_continuous_handle_t) { fake::requireAdcCreator(); ++fake::adcCalls; ++fake::deinits; return fake::ok()?ESP_OK:ESP_FAIL; }
inline esp_err_t adc_continuous_read(adc_continuous_handle_t h, uint8_t *v, uint32_t max, uint32_t *n, uint32_t timeout) {
 fake::requireAdcOwner();
 ++fake::adcCalls; fake::readTimeout=timeout; fake::now+=fake::readAdvance;
 if (fake::overflowDuringRead) { fake::overflowDuringRead=false; fake::callbacks.on_pool_ovf(h,nullptr,nullptr); }
 if (fake::readError != ESP_OK) return fake::readError;
 if (fake::dma.empty()) { *n=0; fake::now+=timeout; return ESP_ERR_TIMEOUT; }
 auto f=fake::dma.front(); fake::dma.pop_front(); *n=static_cast<uint32_t>(std::min<size_t>(max,f.size())); std::memcpy(v,f.data(),*n); return ESP_OK;
}
