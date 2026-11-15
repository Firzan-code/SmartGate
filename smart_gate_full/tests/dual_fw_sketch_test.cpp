#define CONFIG_IDF_TARGET_ESP32S3 1
#ifndef DUAL_TEST_EMPTY_CONFIG
#define WIFI_SSID "TEST_ONLY"
#define WIFI_PASSWORD ""
#define SERVER_IP "192.0.2.1"
#else
#define WIFI_SSID ""
#define WIFI_PASSWORD ""
#define SERVER_IP ""
#endif
#include "Arduino.h"
#include "WiFi.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "esp_adc/adc_continuous.h"
#include "lwip/sockets.h"
#include "tes_dua_model_esp32s3.ino"
#include <cstdlib>
#define CHECK(condition) do { if (!(condition)) { \
 std::fprintf(stderr,"FAIL %s:%d: %s\n",__FILE__,__LINE__,#condition); std::exit(1); } } while(false)
static void setupUnscheduled() { ::setup(); }
static void setupWithAcquisitionSlice() {
 setupUnscheduled();
 fake::runTaskSlice();  // deterministic scheduler starts the real task on identity 2
}
#define setup setupWithAcquisitionSlice

static void empty_configuration_is_inert() {
 setup(); for (unsigned i=0;i<5;++i) loop();
 CHECK(fake::serial.find("CONFIG") != std::string::npos);
 CHECK(fake::adcCalls==0 && fake::taskCalls==0 && fake::queueCalls==0 && fake::wifiCalls==0 && fake::sockets==0);
}
static void dma_startup_contract() {
 setup();
 CHECK(fake::mappedGpio == 1);
 CHECK(fake::adcConfig.sample_freq_hz==16000);
 CHECK(fake::adcConfig.pattern_num==1 && fake::adcConfig.conv_mode==ADC_CONV_SINGLE_UNIT_1);
 CHECK(fake::adcConfig.format==ADC_DIGI_OUTPUT_FORMAT_TYPE2);
 CHECK(fake::adcPattern.unit==ADC_UNIT_1 && fake::adcPattern.channel==ADC_CHANNEL_0);
 CHECK(fake::adcPattern.bit_width==12 && fake::adcPattern.atten==ADC_ATTEN_DB_12);
 CHECK(fake::adcHandleConfig.conv_frame_size==1280);
 CHECK(fake::adcHandleConfig.max_store_buf_size<=5120);
 CHECK(fake::queueCalls==1 && fake::taskCalls==1 && fake::starts==1);
 CHECK(fake::callbacks.on_pool_ovf != nullptr);
 CHECK(fake::sockets==0);
}

static void dma_produces_packet() {
 setup();
 fake::frame();
 fake::runTaskSlice();
 CHECK(dual_fw::audioQueue && dual_fw::audioQueue->data.size()==1);
 dual_fw::QueuedAudio q{};
 CHECK(xQueueReceive(dual_fw::audioQueue,&q,0)==pdTRUE);
 CHECK(std::memcmp(q.packet.bytes,"SGA1",4)==0);
 CHECK(q.packet.bytes[4]==0x78 && q.packet.bytes[7]==0x12);
 CHECK(q.packet.bytes[18]==1 && q.packet.bytes[20]==42);
 CHECK(fake::sent.empty());
}

static void overflow_flushes_old_dma() {
 setup();
 fake::frame(100); fake::runTaskSlice();
 fake::frame();
 const int oldStops=fake::stops, oldFlush=fake::flushes;
 const int oldWrites=fake::serialWrites;
 fake::callbacks.on_pool_ovf(dual_fw::adc,nullptr,nullptr);
 CHECK(fake::stops==oldStops && fake::flushes==oldFlush && fake::serialWrites==oldWrites);
 fake::runTaskSlice();
 CHECK(fake::stops==oldStops+1 && fake::flushes==oldFlush+1 && fake::starts==2);
 CHECK(fake::dma.empty() && dual_fw::audioQueue->data.empty());
 fake::frame(); fake::runTaskSlice();
 dual_fw::QueuedAudio q{}; CHECK(xQueueReceive(dual_fw::audioQueue,&q,0)==pdTRUE);
 CHECK(q.packet.bytes[18]==1);
 CHECK(fake::lifecycle.size()>=4 && fake::lifecycle[1]=="stop" && fake::lifecycle[2]=="flush" && fake::lifecycle[3]=="start");
}

static void stall_discards_buffered_audio() {
 setup();
 fake::frame(); fake::runTaskSlice();
 fake::frame(); fake::now+=250;
 fake::runTaskSlice();
 CHECK(fake::flushes==1 && dual_fw::audioQueue->data.empty());
 fake::frame(); fake::runTaskSlice();
 dual_fw::QueuedAudio q{}; CHECK(xQueueReceive(dual_fw::audioQueue,&q,0)==pdTRUE);
 CHECK(q.packet.bytes[18]==1);
 CHECK(static_cast<uint32_t>(fake::now-q.capturedAt)>=40);
}

static void overflow_during_read_discards_frame() {
 setup(); fake::frame(); fake::overflowDuringRead=true;
 fake::runTaskSlice();
 CHECK(dual_fw::audioQueue->data.empty() && fake::flushes==1);
 fake::frame(); fake::runTaskSlice();
 CHECK(dual_fw::audioQueue->data.size()==1);
}

static void read_error_stops_audio() {
 setup(); fake::readError=ESP_FAIL;
 fake::runTaskSlice();
 CHECK(dual_fw::snapshot().fatal);
 CHECK(dual_fw::audioQueue->data.empty());
}

static void malformed_dma_discards_partial() {
 setup(); fake::frame(319); fake::runTaskSlice();
 fake::dma.push_back(std::vector<uint8_t>{1}); fake::runTaskSlice();
 fake::frame(1); fake::runTaskSlice();
 CHECK(dual_fw::audioQueue->data.empty());
}

static void wifi_retry_nonblocking() {
 setup(); loop();
 CHECK(fake::wifiCalls>0 && fake::wifiBegins==1);
 CHECK(fake::sockets==0);
 for(unsigned i=0;i<20;++i) loop();
 CHECK(fake::wifiBegins==1);
 fake::now+=5000; loop();
 CHECK(fake::wifiBegins==2);
}

static void network_sends_exact_packet() {
 setup(); fake::wifiStatus=WL_CONNECTED; loop();
 CHECK(fake::boundPort==htons(5007) && fake::nonblocking);
 fake::runTaskSlice(); // acknowledge reconnect, stop/flush/restart
 fake::frame(); fake::runTaskSlice(); loop();
 CHECK(fake::sent.size()==1 && fake::sent[0].size()==660);
 CHECK(fake::sentPort==htons(5006) && fake::sentIp==htonl(0xc0000201U));
 CHECK(std::memcmp(fake::sent[0].data(),"SGA1",4)==0);
}

static void reconnect_discards_pending() {
 setup(); fake::frame(); fake::runTaskSlice();
 fake::wifiStatus=WL_CONNECTED; loop();
 CHECK(fake::sent.empty());
 fake::frame(); fake::runTaskSlice(); // recovery must flush this buffered frame
 CHECK(fake::flushes==1 && dual_fw::audioQueue->data.empty());
 fake::frame(); fake::runTaskSlice(); loop();
 CHECK(fake::sent.size()==1 && fake::sent.back()[18]==1);
 fake::wifiStatus=WL_DISCONNECTED; loop();
 fake::frame(); fake::runTaskSlice();
 fake::wifiStatus=WL_CONNECTED; loop();
 CHECK(fake::sent.size()==1 && fake::closes>=1);
}

static void send_failure_flags_next_packet() {
 setup(); fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 fake::frame(); fake::runTaskSlice(); loop();
 fake::frame(); fake::runTaskSlice(); fake::sendResult=-1; loop();
 fake::frame(); fake::runTaskSlice(); fake::sendResult=660; loop();
 CHECK(fake::sent.size()==2);
 CHECK(fake::sent.back()[8]==2 && fake::sent.back()[18]==1);
}

static void queued_audio_expires() {
 setup(); fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 fake::frame(); fake::runTaskSlice();
 fake::now+=151; loop();
 CHECK(fake::sent.empty());
 fake::runTaskSlice(); fake::frame(); fake::runTaskSlice(); loop();
 CHECK(fake::sent.size()==1 && fake::sent.back()[18]==1);
}

static void enqueue_reply(const std::string &text, uint32_t ip=htonl(0xc0000201U), uint16_t port=5006) {
 fake::replies.push_back({std::vector<uint8_t>(text.begin(),text.end()),ip,port});
}
static void valid_reply_reaches_serial() {
 setup(); fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 fake::serial.clear(); fake::now=250;
 enqueue_reply("SGR1 WAJAH=1 SUARA=MENUNGGU");
 for(unsigned i=0;i<12;++i) loop();
 CHECK(fake::serial.find("SGR1 WAJAH=1 SUARA=MENUNGGU")!=std::string::npos);
}

static void reply_requires_exact_peer() {
 setup(); fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 for(unsigned i=0;i<20;++i) loop(); fake::serial.clear();
 enqueue_reply("SGR1 SPOOF_IP",htonl(0xc0000202U));
 for(unsigned i=0;i<10;++i) loop();
 enqueue_reply("SGR1 SPOOF_PORT",htonl(0xc0000201U),5007);
 for(unsigned i=0;i<10;++i) loop();
 CHECK(fake::serial.find("SPOOF_")==std::string::npos);
 CHECK(dual_fw::replyClock.stale(fake::now));
}

static void reply_timeout_visible() {
 setup(); fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 fake::now=0; enqueue_reply("SGR1 ONE_VALID"); loop();
 CHECK(!dual_fw::replyClock.stale(0));
 for(unsigned i=0;i<20;++i) loop(); fake::serial.clear();
 fake::now=3001; for(unsigned i=0;i<20;++i) loop();
 CHECK(fake::serial.find("BASI/MENUNGGU")!=std::string::npos);
 CHECK(fake::serial.find("ONE_VALID")==std::string::npos);
}

static void reply_output_limited() {
 setup(); fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 for(unsigned i=0;i<20;++i) loop(); fake::serial.clear(); fake::now=250;
 for(unsigned i=0;i<100;++i) { enqueue_reply("SGR1 FLOOD"); loop(); }
 size_t n=0, pos=0; while ((pos=fake::serial.find("SGR1 FLOOD",pos))!=std::string::npos) { ++n; ++pos; }
 CHECK(n<=2 && n>=1);
}

static void reconnect_clears_reply() {
 setup(); fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 enqueue_reply("SGR1 OLD_REPLY"); loop(); CHECK(!dual_fw::replyClock.stale(fake::now));
 enqueue_reply("SGR1 BUFFERED_REPLY"); fake::wifiStatus=WL_DISCONNECTED; loop();
 CHECK(dual_fw::replyClock.stale(fake::now));
 fake::wifiStatus=WL_CONNECTED; loop();
 for(unsigned i=0;i<30;++i) loop();
 CHECK(fake::serial.find("BUFFERED_REPLY")==std::string::npos);
}

static void socket_failure_retry_bounded() {
 setup(); fake::wifiStatus=WL_CONNECTED;
 fake::failAt=fake::apiCount+5; // mode+sleep+autoReconnect+event then socket
 loop();
 CHECK(fake::sockets==1);
 for(unsigned i=0;i<20;++i) loop();
 CHECK(fake::sockets==1);
 fake::now+=5000; loop(); CHECK(fake::sockets==2);
}

static void fatal_stops_acquisition() {
 setup(); dual_fw::fail("injected",ESP_FAIL);
 fake::frame(); const int oldCalls=fake::adcCalls;
 fake::runTaskSlice();
 CHECK(fake::stops==1 && !dual_fw::adcRunning);
 CHECK(dual_fw::audioQueue->data.empty());
 const int calls=fake::adcCalls; fake::runTaskSlice(); CHECK(fake::adcCalls==calls && calls>oldCalls);
 for(unsigned i=0;i<20;++i) loop();
 CHECK(fake::serial.find("ERROR")!=std::string::npos && fake::sockets==0);
}

static void startup_failure_matrix() {
 const char *value=std::getenv("DUAL_FAIL_AT"); CHECK(value);
 fake::failAt=std::atoi(value);
 setup(); for(unsigned i=0;i<20;++i) loop();
 CHECK(!dual_fw::active && dual_fw::snapshot().fatal && fake::sockets==0);
 CHECK(dual_fw::audioQueue==nullptr);
 CHECK(fake::serial.find("ERROR")!=std::string::npos);
}

static void receive_error_reported() {
 setup(); fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 for(unsigned i=0;i<20;++i) loop(); fake::serial.clear();
 fake::receiveError=EIO; loop(); fake::receiveError=0;
 for(unsigned i=0;i<20;++i) loop();
 CHECK(fake::serial.find("ERROR UDP read")!=std::string::npos);
 CHECK(dual_fw::replyClock.stale(fake::now));
}

static void diagnostics_bounded() {
 setup(); fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 for(unsigned i=0;i<20;++i) loop(); fake::serial.clear(); fake::sendResult=-1;
 for(unsigned i=0;i<30;++i) {
   fake::frame(); fake::runTaskSlice(); loop();
   fake::now+=15;
 }
 size_t n=0,pos=0; while ((pos=fake::serial.find("ERROR UDP send",pos))!=std::string::npos) { ++n; ++pos; }
 CHECK(n<=3 && n>=1);
}

static void queue_full_preserves_gap_sequence() {
 setup();
 for(unsigned i=0;i<7;++i) { fake::frame(); fake::runTaskSlice(); }
 CHECK(dual_fw::audioQueue->data.size()==6);
 dual_fw::QueuedAudio q{}; CHECK(xQueueReceive(dual_fw::audioQueue,&q,0)==pdTRUE);
 fake::frame(); fake::runTaskSlice();
 while(dual_fw::audioQueue->data.size()>1) CHECK(xQueueReceive(dual_fw::audioQueue,&q,0)==pdTRUE);
 CHECK(xQueueReceive(dual_fw::audioQueue,&q,0)==pdTRUE);
 CHECK(q.packet.bytes[8]==7 && q.packet.bytes[18]==1);
}

static void dma_rejects_wrong_unit_channel() {
 setup(); fake::frame(319); fake::runTaskSlice();
 fake::frame(1,1); fake::runTaskSlice();
 fake::frame(319); fake::runTaskSlice();
 fake::frame(1,0,1); fake::runTaskSlice();
 CHECK(dual_fw::audioQueue->data.empty());
 fake::frame(); fake::runTaskSlice();
 dual_fw::QueuedAudio q{}; CHECK(xQueueReceive(dual_fw::audioQueue,&q,0)==pdTRUE);
 CHECK(q.packet.bytes[18]==1 && q.packet.bytes[20]==42);
}

static void read_timeout_flushes_partial() {
 setup(); fake::frame(319); fake::runTaskSlice();
 fake::readError=ESP_ERR_TIMEOUT; fake::runTaskSlice();
 CHECK(fake::flushes==1 && !dual_fw::snapshot().fatal);
 fake::readError=ESP_OK; fake::frame(1); fake::runTaskSlice();
 CHECK(dual_fw::audioQueue->data.empty());
}

static void slow_read_flushes_frame() {
 setup(); fake::frame(); fake::readAdvance=41; fake::runTaskSlice();
 CHECK(fake::flushes==1 && dual_fw::audioQueue->data.empty());
}

static void oversize_then_valid_reply() {
 setup(); fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 for(unsigned i=0;i<20;++i) loop(); fake::serial.clear();
 enqueue_reply(std::string("SGR1 ")+std::string(5000,'x'));
 enqueue_reply(std::string("SGR1 ")+std::string(508,'y'));
 enqueue_reply("SGR1 AFTER_OVERSIZE");
 for(unsigned i=0;i<30;++i) loop();
 CHECK(fake::serial.find("AFTER_OVERSIZE")!=std::string::npos);
 CHECK(fake::serial.find("xxxxx")==std::string::npos && fake::serial.find("yyyyy")==std::string::npos);
}

static void socket_reopen_rejects_pending_audio() {
 setup(); fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 fake::receiveError=EIO; loop(); fake::receiveError=0;
 fake::now+=5000; fake::runTaskSlice();
 fake::frame(); fake::runTaskSlice(); loop();
 CHECK(fake::sent.empty());
 CHECK(dual_fw::audioQueue->data.empty());
}

static void wifi_uses_explicit_retry_only() {
 setup(); loop();
 CHECK(!fake::persistent && !fake::autoReconnect);
}

static void wifi_event_between_loops_resets_stream() {
 setup(); fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 const uint32_t epoch=dual_fw::snapshot().epoch;
 fake::frame(); fake::runTaskSlice();
 if(fake::wifiEvent) fake::wifiEvent(ARDUINO_EVENT_WIFI_STA_DISCONNECTED);
 loop();
 CHECK(dual_fw::snapshot().epoch!=epoch);
 CHECK(fake::sent.empty());
 CHECK(dual_fw::audioQueue->data.empty());
}

static void parser_stall_cannot_refresh_samples() {
 setup(); fake::frame();
 // lock5 is post-read snapshot: emulate suspension before parsing the DMA buffer.
 fake::jumpAtEnter=fake::enters+5; fake::jumpMs=250;
 fake::runTaskSlice();
 if(!dual_fw::audioQueue->data.empty()) {
   dual_fw::QueuedAudio q{}; CHECK(xQueueReceive(dual_fw::audioQueue,&q,0)==pdTRUE);
   CHECK(static_cast<uint32_t>(fake::now-q.capturedAt)>150);
 }
}

static void raw_type2_layout_matches_sdk() {
 setup();
 std::vector<uint8_t> raw(1280,0);
 const uint32_t value=42U | (1U << 17); // ADC2 in S3 TYPE2, not bit16
 for(unsigned i=0;i<320;++i) std::memcpy(raw.data()+i*4,&value,4);
 fake::dma.push_back(raw); fake::runTaskSlice();
 CHECK(dual_fw::audioQueue->data.empty());
}

static void reply_processing_budget() {
 setup(); fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 for(unsigned i=0;i<20;++i) enqueue_reply("SGR1 BUDGET");
 const int before=fake::receives;
 fake::frame(); fake::runTaskSlice(); loop();
 CHECK(fake::receives-before<=4 && fake::sent.size()==1);
}

static void serial_backpressure_does_not_block_capture() {
 fake::serialSpace=0; setup();
 for(unsigned i=0;i<4;++i) { fake::frame(); fake::runTaskSlice(); loop(); }
 CHECK(fake::serialWrites==0 && dual_fw::audioQueue->data.size()==4);
}

static void recovery_failure_matrix() {
 setup(); const char *s=std::getenv("DUAL_FAIL_AT"); CHECK(s);
 fake::failAt=fake::apiCount+std::atoi(s);
 fake::callbacks.on_pool_ovf(dual_fw::adc,nullptr,nullptr); fake::runTaskSlice();
 CHECK(dual_fw::snapshot().fatal && dual_fw::audioQueue->data.empty());
 fake::runTaskSlice();
 for(unsigned i=0;i<20;++i) loop();
 CHECK(fake::serial.find("ERROR")!=std::string::npos && fake::sent.empty());
}

static void network_setup_failure_matrix() {
 setup(); const char *s=std::getenv("DUAL_FAIL_AT"); CHECK(s);
 fake::failAt=fake::apiCount+std::atoi(s); fake::wifiStatus=WL_CONNECTED; loop();
 CHECK(dual_fw::snapshot().fatal || dual_fw::udp<0);
 CHECK(fake::sent.empty());
}

static void queue_age_wrap_boundary() {
 setup(); fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 fake::now=UINT32_MAX-70; dual_fw::lastAcquisition=fake::now;
 fake::frame(); fake::runTaskSlice();
 fake::now=19; loop(); // age=150, allow
 CHECK(fake::sent.size()==1);
 fake::now=UINT32_MAX-70; dual_fw::lastAcquisition=fake::now;
 fake::frame(); fake::runTaskSlice();
 fake::now=20; loop(); // age=151, reject
 CHECK(fake::sent.size()==1);
}

static void stale_discards_pending_serial_summary() {
 setup(); fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 fake::serialSpace=0; enqueue_reply("SGR1 HELD_PREDICTION"); loop();
 fake::now+=3001; loop(); fake::serialSpace=4096;
 for(unsigned i=0;i<20;++i) loop();
 CHECK(fake::serial.find("HELD_PREDICTION")==std::string::npos);
 CHECK(fake::serial.find("BASI/MENUNGGU")!=std::string::npos);
}

static void startup_bad_mapping_is_inert() {
 fake::badMapping=true; setup(); for(unsigned i=0;i<20;++i) loop();
 CHECK(!dual_fw::active && dual_fw::snapshot().fatal);
 CHECK(fake::queueCalls==0 && fake::taskCalls==1 && fake::sockets==0 && fake::sent.empty());
}

static void empty_config_repeats_instructions() {
 setup(); for(unsigned i=0;i<20;++i) loop(); fake::serial.clear();
 fake::now+=3000; for(unsigned i=0;i<20;++i) loop();
 CHECK(fake::serial.find("CONFIG")!=std::string::npos);
 CHECK(fake::adcCalls==0 && fake::wifiCalls==0 && fake::taskCalls==0);
}

static void dma_read_allows_frame_plus_margin() {
 setup(); fake::frame(); fake::runTaskSlice();
 CHECK(fake::readTimeout>=25 && fake::readTimeout<=40);
}

static void summary_rate_survives_reconnect() {
 setup(); fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 for(unsigned i=0;i<20;++i) loop(); fake::serial.clear();
 enqueue_reply("SGR1 RATE_A"); loop();
 fake::wifiStatus=WL_DISCONNECTED; loop();
 fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 enqueue_reply("SGR1 RATE_B"); for(unsigned i=0;i<20;++i) loop();
 size_t n=0,pos=0; while ((pos=fake::serial.find("SGR1 RATE_",pos))!=std::string::npos) { ++n; ++pos; }
 CHECK(n<=1);
}

static void short_send_cannot_succeed() {
 setup(); fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 fake::frame(); fake::runTaskSlice(); fake::sendResult=659; loop();
 CHECK(fake::sent.empty());
 fake::frame(); fake::runTaskSlice(); fake::sendResult=660; loop();
 CHECK(fake::sent.size()==1 && fake::sent.back()[8]==1 && fake::sent.back()[18]==1);
}

static void link_flicker_diagnostics_bounded() {
 setup(); fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 for(unsigned i=0;i<20;++i) loop(); fake::serial.clear();
 for(unsigned i=0;i<30;++i) {
   fake::wifiStatus=(i%2)?WL_CONNECTED:WL_DISCONNECTED;
   loop(); fake::runTaskSlice(); fake::now+=10;
 }
 CHECK(fake::serial.size()<400);
}

static void acquisition_gap_clears_reply() {
 setup(); fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 enqueue_reply("SGR1 BEFORE_GAP"); loop(); CHECK(!dual_fw::replyClock.stale(fake::now));
 fake::callbacks.on_pool_ovf(dual_fw::adc,nullptr,nullptr); fake::runTaskSlice();
 loop();
 CHECK(dual_fw::replyClock.stale(fake::now));
}

static void gap_discards_buffered_reply() {
 setup(); fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 enqueue_reply("SGR1 OLD_DMA_REPLY");
 fake::callbacks.on_pool_ovf(dual_fw::adc,nullptr,nullptr); fake::runTaskSlice();
 loop();
 CHECK(dual_fw::replyClock.stale(fake::now));
 CHECK(fake::serial.find("OLD_DMA_REPLY")==std::string::npos);
}

static void recovery_race_drops_dequeued_audio() {
 setup(); fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 fake::frame(); fake::runTaskSlice();
 fake::afterDequeue=[]() { fake::callbacks.on_pool_ovf(dual_fw::adc,nullptr,nullptr); fake::runTaskSlice(); };
 loop();
 CHECK(fake::sent.empty());
}

static void dequeued_audio_reply_epoch(bool recover) {
 setup(); fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 fake::serial.clear(); fake::frame(); fake::runTaskSlice();
 CHECK(dual_fw::audioQueue->data.size()==1);
 const uint32_t before=dual_fw::snapshot().epoch;
 enqueue_reply("SGR1 OLD_BUFFERED_RESULT");
 if(recover) fake::afterDequeue=[]() {
   fake::callbacks.on_pool_ovf(dual_fw::adc,nullptr,nullptr);
   fake::runTaskSlice();
 };
 loop();
 std::printf("recover=%d epoch_before=%u epoch_after=%u network_epoch=%u stale=%d sent=%zu serial=[%s]\n",
   recover,before,dual_fw::snapshot().epoch,dual_fw::networkEpoch,
   dual_fw::replyClock.stale(fake::now),fake::sent.size(),fake::serial.c_str());
 if(recover) {
   CHECK(dual_fw::snapshot().epoch!=before && fake::sent.empty());
   CHECK(dual_fw::replyClock.stale(fake::now));
   CHECK(fake::serial.find("OLD_BUFFERED_RESULT")==std::string::npos);
   // Recovery and a subsequent disconnect must not strand the stream.
   loop(); fake::frame(); fake::runTaskSlice(); loop();
   CHECK(fake::sent.size()==1);
   fake::wifiStatus=WL_DISCONNECTED; loop();
   fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
   fake::frame(); fake::runTaskSlice(); loop();
   CHECK(fake::sent.size()==2);
 } else {
   CHECK(dual_fw::snapshot().epoch==before && fake::sent.size()==1);
   CHECK(!dual_fw::replyClock.stale(fake::now));
   CHECK(fake::serial.find("OLD_BUFFERED_RESULT")!=std::string::npos);
 }
}
static void unchanged_epoch_reply_control() { dequeued_audio_reply_epoch(false); }
static void recovery_race_discards_buffered_reply() { dequeued_audio_reply_epoch(true); }

static void recovery_during_recv_discards_reply() {
 setup(); fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 fake::serial.clear(); const uint32_t before=dual_fw::snapshot().epoch;
 enqueue_reply("SGR1 RECOVERED_DURING_RECV");
 fake::duringReceive=[]() {
   fake::callbacks.on_pool_ovf(dual_fw::adc,nullptr,nullptr); fake::runTaskSlice();
 };
 loop();
 CHECK(dual_fw::snapshot().epoch!=before);
 CHECK(dual_fw::replyClock.stale(fake::now));
 CHECK(fake::serial.find("RECOVERED_DURING_RECV")==std::string::npos);
}

static void recovery_before_serial_discards_summary() {
 setup(); fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 fake::serial.clear();
 fake::serialSpace=0; enqueue_reply("SGR1 HELD_BEFORE_RECOVERY"); loop();
 CHECK(dual_fw::serialIsSummary && !dual_fw::replyClock.stale(fake::now));
 const uint32_t before=dual_fw::snapshot().epoch;
 fake::duringSerialSpace=[]() {
   fake::callbacks.on_pool_ovf(dual_fw::adc,nullptr,nullptr); fake::runTaskSlice();
 };
 fake::serialSpace=4096; loop();
 CHECK(dual_fw::snapshot().epoch!=before);
 CHECK(fake::serial.find("HELD_BEFORE_RECOVERY")==std::string::npos);
 CHECK(dual_fw::replyClock.stale(fake::now));
}

static void source_fault_before_serial(void (*fault)()) {
 setup(); fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 fake::serial.clear();
 fake::serialSpace=0; enqueue_reply("SGR1 HELD_BEFORE_FAULT"); loop();
 CHECK(dual_fw::serialIsSummary && !dual_fw::replyClock.stale(fake::now));
 fake::duringSerialSpace=fault; fake::serialSpace=4096; loop();
 CHECK(fake::serial.find("HELD_BEFORE_FAULT")==std::string::npos);
 CHECK(dual_fw::replyClock.stale(fake::now));
}
static void fatal_before_serial_discards_summary() {
 source_fault_before_serial([]() { dual_fw::fail("during Serial space",ESP_FAIL); });
}
static void overflow_before_serial_discards_summary() {
 source_fault_before_serial([]() { fake::callbacks.on_pool_ovf(dual_fw::adc,nullptr,nullptr); });
}
static void linklost_before_serial_discards_summary() {
 source_fault_before_serial([]() { CHECK(fake::wifiEvent); fake::wifiEvent(ARDUINO_EVENT_WIFI_STA_DISCONNECTED); });
}

static void stalled_network_does_not_print_expired_reply() {
 setup(); fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 for(unsigned i=0;i<20;++i) loop(); fake::serial.clear();
 fake::serialSpaceAdvance=3001; enqueue_reply("SGR1 EXPIRED_BEFORE_WRITE"); loop();
 CHECK(fake::serial.find("EXPIRED_BEFORE_WRITE")==std::string::npos);
}

static void adc_startup_waits_for_owner_task() {
 setupUnscheduled();
 CHECK(fake::starts==0 && fake::adcCalls==0 && !dual_fw::active);
 for(unsigned i=0;i<10;++i) loop();
 CHECK(fake::wifiCalls==0 && fake::sockets==0 && !dual_fw::active);
 fake::runTaskSlice();
 CHECK(dual_fw::snapshot().adcReady && fake::adcOwner==fake::acquisitionTaskId);
 CHECK(!dual_fw::active);
 loop();
 CHECK(dual_fw::active && fake::wifiCalls>0);
}

static void adc_reconnect_and_fatal_keep_owner() {
 setup(); fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
 for(unsigned i=0;i<12;++i) {
   fake::wifiStatus=WL_DISCONNECTED; loop(); fake::runTaskSlice();
   fake::wifiStatus=WL_CONNECTED; loop(); fake::runTaskSlice(); loop();
   fake::frame(); fake::runTaskSlice(); loop();
 }
 CHECK(!fake::sent.empty() && !dual_fw::snapshot().fatal);
 dual_fw::fail("owner regression",ESP_FAIL); fake::runTaskSlice();
 CHECK(!fake::adcStarted && fake::adcOwner==0 && !dual_fw::adcRunning);
 for(uintptr_t task:fake::lifecycleTasks) CHECK(task==fake::acquisitionTaskId);
}

static void adc_recovery_keeps_start_stop_owner() {
 fake::enforceOwner=true;
 setupUnscheduled();
 // Run the actual stored task entry, not an imitation of firmware logic.
 fake::runTaskSlice();
 CHECK(fake::starts>=1);
 const int stops=fake::stops;
 fake::callbacks.on_pool_ovf(dual_fw::adc,nullptr,nullptr);
 fake::runTaskSlice();
 CHECK(fake::stops==stops+1 && fake::flushes>=1);
 for(uintptr_t task:fake::lifecycleTasks) CHECK(task==fake::acquisitionTaskId);
 CHECK(!dual_fw::snapshot().fatal && dual_fw::adcRunning);
}

struct Test { const char *name; void (*run)(); };
static const Test cases[] = {
 {"adc_startup_waits_for_owner_task", adc_startup_waits_for_owner_task},
 {"adc_reconnect_and_fatal_keep_owner", adc_reconnect_and_fatal_keep_owner},
 {"adc_recovery_keeps_start_stop_owner", adc_recovery_keeps_start_stop_owner},
 {"empty_configuration_is_inert", empty_configuration_is_inert},
 {"dma_startup_contract", dma_startup_contract},
 {"dma_produces_packet", dma_produces_packet},
 {"overflow_flushes_old_dma", overflow_flushes_old_dma},
 {"stall_discards_buffered_audio", stall_discards_buffered_audio},
 {"overflow_during_read_discards_frame", overflow_during_read_discards_frame},
 {"read_error_stops_audio", read_error_stops_audio},
 {"malformed_dma_discards_partial", malformed_dma_discards_partial},
 {"wifi_retry_nonblocking", wifi_retry_nonblocking},
 {"network_sends_exact_packet", network_sends_exact_packet},
 {"reconnect_discards_pending", reconnect_discards_pending},
 {"send_failure_flags_next_packet", send_failure_flags_next_packet},
 {"queued_audio_expires", queued_audio_expires},
 {"valid_reply_reaches_serial", valid_reply_reaches_serial},
 {"reply_requires_exact_peer", reply_requires_exact_peer},
 {"reply_timeout_visible", reply_timeout_visible},
 {"reply_output_limited", reply_output_limited},
 {"reconnect_clears_reply", reconnect_clears_reply},
 {"socket_failure_retry_bounded", socket_failure_retry_bounded},
 {"fatal_stops_acquisition", fatal_stops_acquisition},
 {"startup_failure_matrix", startup_failure_matrix},
 {"receive_error_reported", receive_error_reported},
 {"diagnostics_bounded", diagnostics_bounded},
 {"queue_full_preserves_gap_sequence", queue_full_preserves_gap_sequence},
 {"dma_rejects_wrong_unit_channel", dma_rejects_wrong_unit_channel},
 {"read_timeout_flushes_partial", read_timeout_flushes_partial},
 {"slow_read_flushes_frame", slow_read_flushes_frame},
 {"oversize_then_valid_reply", oversize_then_valid_reply},
 {"socket_reopen_rejects_pending_audio", socket_reopen_rejects_pending_audio},
 {"wifi_uses_explicit_retry_only", wifi_uses_explicit_retry_only},
 {"wifi_event_between_loops_resets_stream", wifi_event_between_loops_resets_stream},
 {"parser_stall_cannot_refresh_samples", parser_stall_cannot_refresh_samples},
 {"raw_type2_layout_matches_sdk", raw_type2_layout_matches_sdk},
 {"reply_processing_budget", reply_processing_budget},
 {"serial_backpressure_does_not_block_capture", serial_backpressure_does_not_block_capture},
 {"recovery_failure_matrix", recovery_failure_matrix},
 {"network_setup_failure_matrix", network_setup_failure_matrix},
 {"queue_age_wrap_boundary", queue_age_wrap_boundary},
 {"stale_discards_pending_serial_summary", stale_discards_pending_serial_summary},
 {"startup_bad_mapping_is_inert", startup_bad_mapping_is_inert},
 {"empty_config_repeats_instructions", empty_config_repeats_instructions},
 {"dma_read_allows_frame_plus_margin", dma_read_allows_frame_plus_margin},
 {"summary_rate_survives_reconnect", summary_rate_survives_reconnect},
 {"short_send_cannot_succeed", short_send_cannot_succeed},
 {"link_flicker_diagnostics_bounded", link_flicker_diagnostics_bounded},
 {"acquisition_gap_clears_reply", acquisition_gap_clears_reply},
 {"gap_discards_buffered_reply", gap_discards_buffered_reply},
 {"recovery_race_drops_dequeued_audio", recovery_race_drops_dequeued_audio},
 {"unchanged_epoch_reply_control", unchanged_epoch_reply_control},
 {"recovery_race_discards_buffered_reply", recovery_race_discards_buffered_reply},
 {"recovery_during_recv_discards_reply", recovery_during_recv_discards_reply},
 {"recovery_before_serial_discards_summary", recovery_before_serial_discards_summary},
 {"fatal_before_serial_discards_summary", fatal_before_serial_discards_summary},
 {"overflow_before_serial_discards_summary", overflow_before_serial_discards_summary},
 {"linklost_before_serial_discards_summary", linklost_before_serial_discards_summary},
 {"stalled_network_does_not_print_expired_reply", stalled_network_does_not_print_expired_reply},
};
int main(int argc, char **argv) {
 const char *name=argc>1?argv[1]:"--list";
 if (std::strcmp(name,"--list")==0) { for(const auto &t:cases) std::puts(t.name); return 0; }
 for(const auto &t:cases) if(std::strcmp(name,t.name)==0) {
   t.run(); std::printf("PASS %s\n",name); return 0;
 }
 std::fprintf(stderr,"Unknown test: %s\n",name); return 2;
}
