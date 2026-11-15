#pragma once
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cstdio>
#include <string>
#include <vector>
#include <deque>
#include <utility>
#define OUTPUT 1
#define LOW 0
extern uint32_t fake_now;
extern int attach_calls, write_calls, detach_calls, last_pin;
extern uint32_t last_duty;
extern bool attach_ok, write_ok;
inline uint32_t millis() { return fake_now; }
inline void delay(uint32_t ms) { fake_now += ms; }
inline void pinMode(int, int) {}
inline void digitalWrite(int, int) {}
inline bool ledcAttach(int pin, uint32_t hz, uint8_t bits) {
    ++attach_calls; last_pin = pin;
    return hz == 50 && bits == 14 && attach_ok;
}
inline bool ledcWrite(int pin, uint32_t duty) {
    ++write_calls; last_pin = pin; last_duty = duty; return write_ok;
}
inline bool ledcDetach(int pin) { ++detach_calls; last_pin = pin; return true; }
struct SerialMock {
    void begin(int) {}
    template<class... T> void printf(const char*, T...) {}
    void println(const char*) {}
};
extern SerialMock Serial;
