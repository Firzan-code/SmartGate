#pragma once
#include "Arduino.h"
#define WIFI_STA 1
#define WL_CONNECTED 3
struct IPAddress {
    uint8_t b[4] = {0,0,0,0};
    IPAddress() = default;
    IPAddress(uint8_t a, uint8_t c, uint8_t d, uint8_t e) : b{a,c,d,e} {}
    bool fromString(const char* text) {
        unsigned a,c,d,e; char rest;
        if (std::sscanf(text, "%u.%u.%u.%u%c", &a,&c,&d,&e,&rest) != 4 || a>255 || c>255 || d>255 || e>255) return false;
        b[0]=a; b[1]=c; b[2]=d; b[3]=e; return true;
    }
    uint8_t operator[](size_t i) const { return b[i]; }
    bool operator==(const IPAddress& other) const { return std::memcmp(b,other.b,4)==0; }
    bool operator!=(const IPAddress& other) const { return !(*this==other); }
    std::string toString() const {
        char out[32]; std::snprintf(out,sizeof(out),"%u.%u.%u.%u",b[0],b[1],b[2],b[3]); return out;
    }
};
struct WiFiMock {
    int status_value=WL_CONNECTED, begin_calls=0;
    void mode(int) {}
    void setSleep(bool) {}
    void begin(const char*,const char*) { ++begin_calls; }
    int status() const { return status_value; }
    IPAddress localIP() const { return IPAddress(192,0,2,10); }
};
extern WiFiMock WiFi;
