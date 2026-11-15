#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include <deque>
#include <algorithm>
#include <cstdio>
#include <cerrno>
#define IRAM_ATTR
#define DRAM_ATTR
namespace fake {
inline uint32_t now = 0;
inline uint32_t jumpMs = 0;
inline std::string serial;
inline int serialSpace = 4096;
inline int serialWrites = 0;
inline uint32_t serialSpaceAdvance = 0;
inline void (*duringSerialSpace)() = nullptr;
inline int adcCalls = 0, taskCalls = 0, queueCalls = 0, wifiCalls = 0;
inline int failAt = 0, apiCount = 0;
inline bool ok() { return ++apiCount != failAt; }
}
inline uint32_t millis() { return fake::now; }
inline void delay(uint32_t ms) { fake::now += ms; }
struct FakeSerial {
 void begin(unsigned long) {}
 int availableForWrite() {
   fake::now += fake::serialSpaceAdvance;
   if(fake::duringSerialSpace) { auto hook=fake::duringSerialSpace; fake::duringSerialSpace=nullptr; hook(); }
   return fake::serialSpace;
 }
 size_t write(const uint8_t *p, size_t n) { ++fake::serialWrites; fake::serial.append(reinterpret_cast<const char *>(p), n); return n; }
 size_t write(const char *p, size_t n) { return write(reinterpret_cast<const uint8_t *>(p), n); }
};
inline FakeSerial Serial;
