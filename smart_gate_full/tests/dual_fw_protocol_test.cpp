#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

#define DUAL_PROTOCOL_ONLY
#include "tes_dua_model_esp32s3.ino"

#define CHECK(condition) do { if (!(condition)) { \
  std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #condition); \
  std::exit(1); } } while (false)

static void packet_wire_format() {
  dual::Packetizer packetizer(0x12345678U);
  std::vector<dual::AudioPacket> packets;
  const auto sink = [&](const dual::AudioPacket &packet) {
    packets.push_back(packet);
    return true;
  };
  for (unsigned i = 0; i < 320; ++i) packetizer.push(0, 0, i, sink);
  CHECK(packets.size() == 1);
  CHECK(sizeof(packets[0].bytes) == 660);
  const unsigned char expected[20] = {
    'S', 'G', 'A', '1', 0x78, 0x56, 0x34, 0x12,
    0, 0, 0, 0, 0x80, 0x3e, 0, 0, 0x40, 0x01, 1, 0
  };
  CHECK(std::memcmp(packets[0].bytes, expected, sizeof(expected)) == 0);
  for (unsigned i = 0; i < 320; ++i) {
    CHECK(packets[0].bytes[20 + i * 2] == (i & 255));
    CHECK(packets[0].bytes[21 + i * 2] == (i >> 8));
  }
}

static void invalid_samples_reset_partial() {
  for (unsigned kind = 0; kind < 3; ++kind) {
    dual::Packetizer p(7);
    std::vector<dual::AudioPacket> packets;
    auto sink = [&](const dual::AudioPacket &v) { packets.push_back(v); return true; };
    for (unsigned i = 0; i < 319; ++i) p.push(0, 0, 5, sink);
    p.push(kind == 0 ? 1 : 0, kind == 1 ? 1 : 0, kind == 2 ? 4096 : 5, sink);
    CHECK(packets.empty());
    for (unsigned i = 0; i < 320; ++i) p.push(0, 0, 4095, sink);
    CHECK(packets.size() == 1);
    CHECK(packets[0].bytes[18] == 1);
    CHECK(packets[0].bytes[20] == 255 && packets[0].bytes[21] == 15);
  }
}

static void reset_discards_partial() {
  dual::Packetizer p(17);
  std::vector<dual::AudioPacket> packets;
  auto sink = [&](const dual::AudioPacket &v) { packets.push_back(v); return true; };
  for (unsigned i = 0; i < 320; ++i) p.push(0, 0, 0, sink);
  for (unsigned i = 0; i < 319; ++i) p.push(0, 0, 8, sink);
  p.markDiscontinuity();
  p.push(0, 0, 9, sink);
  CHECK(packets.size() == 1);
  for (unsigned i = 0; i < 319; ++i) p.push(0, 0, 9, sink);
  CHECK(packets.size() == 2);
  CHECK(packets[1].bytes[8] == 1 && packets[1].bytes[18] == 1);
  CHECK(packets[1].bytes[20] == 9);
}

static void completed_packet_failure_sequence() {
  dual::Packetizer p(12);
  std::vector<dual::AudioPacket> packets;
  auto sink = [&](const dual::AudioPacket &v) { packets.push_back(v); return packets.size() != 2; };
  for (unsigned i = 0; i < 4 * 320; ++i) p.push(0, 0, 4095, sink);
  CHECK(packets.size() == 4);
  for (unsigned i = 0; i < 4; ++i) CHECK(packets[i].bytes[8] == i);
  CHECK(packets[0].bytes[18] == 1);
  CHECK(packets[1].bytes[18] == 0);
  CHECK(packets[2].bytes[18] == 1);
  CHECK(packets[3].bytes[18] == 0);
}

static void sequence_wrap() {
  dual::Packetizer p(9, UINT32_MAX);
  std::vector<dual::AudioPacket> packets;
  auto sink = [&](const dual::AudioPacket &v) { packets.push_back(v); return false; };
  for (unsigned i = 0; i < 640; ++i) p.push(0, 0, i % 4096, sink);
  CHECK(packets[0].bytes[8] == 255 && packets[0].bytes[11] == 255);
  CHECK(packets[1].bytes[8] == 0 && packets[1].bytes[11] == 0);
  CHECK(packets[1].bytes[18] == 1);
}

static bool parse_reply(const uint8_t *bytes, size_t n, char *out, size_t cap) {
  return dual::parseReply(bytes, n, out, cap);
}
static void reply_accepts_line() {
  const char text[] = "SGR1 WAJAH=1 MATA=BUKA SUARA=MENUNGGU";
  char out[513] = {};
  CHECK(parse_reply(reinterpret_cast<const uint8_t *>(text), std::strlen(text), out, sizeof(out)));
  CHECK(std::strcmp(out, text) == 0);
}

static void reply_rejects_bad_frames() {
  char out[513] = {};
  const char *bad[] = {"", "SGR1 ", "SGR1  ", "SGR2 hello", "SGR1 x\ny", "SGR1 x\ry", "SGR1 \tx", "SGR1 \x7f", "SGR1 \x80"};
  for (const auto *v : bad) CHECK(!parse_reply(reinterpret_cast<const uint8_t *>(v), std::strlen(v), out, sizeof(out)));
  const uint8_t nul[] = {'S','G','R','1',' ','x',0,'y'};
  CHECK(!parse_reply(nul, sizeof(nul), out, sizeof(out)));
  std::vector<uint8_t> max(512, 'x'); std::memcpy(max.data(), "SGR1 ", 5);
  CHECK(parse_reply(max.data(), max.size(), out, sizeof(out)));
  CHECK(!parse_reply(max.data(), max.size(), out, 512));
  max.push_back('x');
  CHECK(!parse_reply(max.data(), max.size(), out, sizeof(out)));
  CHECK(!parse_reply(nullptr, 10, out, sizeof(out)));
}

static void reply_timeout_wrap() {
  dual::ReplyClock clock;
  CHECK(clock.stale(0));
  clock.accept(0);
  CHECK(!clock.stale(0) && !clock.stale(3000));
  CHECK(clock.stale(3001));
  clock.accept(UINT32_MAX - 100);
  CHECK(!clock.stale(2899));
  CHECK(clock.stale(2900));
  clock.clear();
  CHECK(clock.stale(0));
}

static void actuator_command_parser_is_exact() {
  using dual::ActuatorCommand;
  CHECK(dual::parseActuatorCommand("SGR1 SUARA=SIRENE AKTUATOR=OPEN") == ActuatorCommand::open);
  CHECK(dual::parseActuatorCommand("SGR1 AKTUATOR=HOLD X=1") == ActuatorCommand::hold);
  CHECK(dual::parseActuatorCommand("SGR1 AKTUATOR=DISABLED") == ActuatorCommand::disable);
  CHECK(dual::parseActuatorCommand("SGR1 AKTUATOR=OPENED") == ActuatorCommand::unknown);
  CHECK(dual::parseActuatorCommand("SGR1 XAKTUATOR=OPEN") == ActuatorCommand::unknown);
  CHECK(dual::parseActuatorCommand("SGR1 SUARA=SIRENE") == ActuatorCommand::unknown);
  CHECK(dual::parseActuatorCommand(nullptr) == ActuatorCommand::unknown);
}

static void servo_policy_timeout_cooldown_and_clear() {
  using dual::ActuatorCommand; using dual::ServoAction; using dual::ServoState;
  dual::ServoPolicy policy(5000, 10000);
  CHECK(policy.start(10) == ServoAction::none && policy.state() == ServoState::disabled);
  CHECK(policy.command(11, ActuatorCommand::open) == ServoAction::none);
  CHECK(policy.command(12, ActuatorCommand::hold) == ServoAction::close);
  CHECK(policy.state() == ServoState::closed);
  CHECK(policy.command(13, ActuatorCommand::open) == ServoAction::open);
  CHECK(policy.command(14, ActuatorCommand::open) == ServoAction::none);
  CHECK(policy.tick(5012, true) == ServoAction::none);
  CHECK(policy.tick(5013, true) == ServoAction::close && policy.state() == ServoState::cooldown);
  CHECK(policy.command(5014, ActuatorCommand::open) == ServoAction::none);
  CHECK(policy.command(5015, ActuatorCommand::hold) == ServoAction::none);
  CHECK(policy.tick(15012, true) == ServoAction::none && policy.state() == ServoState::cooldown);
  CHECK(policy.tick(15013, true) == ServoAction::none && policy.state() == ServoState::closed);
  CHECK(policy.command(15014, ActuatorCommand::open) == ServoAction::open);
  CHECK(policy.command(15015, ActuatorCommand::disable) == ServoAction::release);
  CHECK(policy.state() == ServoState::disabled);
}

static void servo_policy_link_loss_fault_and_wrap() {
  using dual::ActuatorCommand; using dual::ServoAction; using dual::ServoState;
  dual::ServoPolicy policy(5000, 10000);
  policy.start(UINT32_MAX - 100); policy.command(UINT32_MAX - 99, ActuatorCommand::hold);
  CHECK(policy.command(UINT32_MAX - 98, ActuatorCommand::open) == ServoAction::open);
  CHECK(policy.tick(4900, true) == ServoAction::none);
  CHECK(policy.tick(4901, false) == ServoAction::close);
  CHECK(policy.fault(4902) == ServoAction::release && policy.state() == ServoState::error);
  CHECK(policy.command(4903, ActuatorCommand::hold) == ServoAction::none);
  CHECK((policy.telemetryFlags() & dual::kServoPresent) != 0);
  CHECK(((policy.telemetryFlags() & dual::kServoStateMask) >> dual::kServoStateShift) == 4);
}

static void invalid_after_live_marks_discontinuity() {
  dual::Packetizer p(8); std::vector<dual::AudioPacket> packets;
  auto sink = [&](const dual::AudioPacket &v) { packets.push_back(v); return true; };
  for (unsigned i=0; i<320; ++i) p.push(0,0,0,sink);
  p.push(1,0,0,sink);
  for (unsigned i=0; i<640; ++i) p.push(0,0,4095,sink);
  CHECK(packets.size()==3 && packets[1].bytes[8]==1);
  CHECK(packets[1].bytes[18]==1 && packets[2].bytes[18]==0 && packets[2].bytes[19]==0);
}

struct Test { const char *name; void (*run)(); };
static const Test cases[] = {
  {"servo_policy_link_loss_fault_and_wrap", servo_policy_link_loss_fault_and_wrap},
  {"servo_policy_timeout_cooldown_and_clear", servo_policy_timeout_cooldown_and_clear},
  {"actuator_command_parser_is_exact", actuator_command_parser_is_exact},
  {"invalid_after_live_marks_discontinuity", invalid_after_live_marks_discontinuity},
  {"reply_timeout_wrap", reply_timeout_wrap},
  {"reply_rejects_bad_frames", reply_rejects_bad_frames},
  {"reply_accepts_line", reply_accepts_line},
  {"sequence_wrap", sequence_wrap},
  {"completed_packet_failure_sequence", completed_packet_failure_sequence},
  {"reset_discards_partial", reset_discards_partial},
  {"packet_wire_format", packet_wire_format},
  {"invalid_samples_reset_partial", invalid_samples_reset_partial},
};
int main(int argc, char **argv) {
  const char *name = argc > 1 ? argv[1] : "all";
  bool found = false;
  for (const auto &c : cases) {
    if (std::strcmp(name, "all") == 0 || std::strcmp(name, c.name) == 0) {
      c.run(); std::printf("PASS %s\n", c.name); found = true;
    }
  }
  if (!found) { std::fprintf(stderr, "Unknown test: %s\n", name); return 2; }
}
