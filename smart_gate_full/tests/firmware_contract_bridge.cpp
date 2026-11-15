// Host-only bridge. Explicit input fixtures, never accesses ESP hardware.
#include <cstdio>
#include <cstdint>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif
#define DUAL_PROTOCOL_ONLY
#include "tes_dua_model_esp32s3.ino"

int main() {
#ifdef _WIN32
  if (_setmode(_fileno(stdin), _O_BINARY) == -1 ||
      _setmode(_fileno(stdout), _O_BINARY) == -1) return 2;
#endif
  dual::Packetizer packetizer(0x12345678U);
  bool ok = true;
  const auto emit = [&](const dual::AudioPacket &packet) {
    ok = std::fwrite(packet.bytes, 1, sizeof(packet.bytes), stdout) == sizeof(packet.bytes);
    return ok;
  };
  for (;;) {
    const int low = std::fgetc(stdin);
    if (low == EOF) break;
    const int high = std::fgetc(stdin);
    if (high == EOF) return 2;
    const unsigned raw = static_cast<unsigned>(low) | (static_cast<unsigned>(high) << 8);
    packetizer.push(0, 0, raw, emit);
    if (!ok) return 3;
  }
  return std::ferror(stdin) || std::fflush(stdout) != 0 ? 4 : 0;
}
