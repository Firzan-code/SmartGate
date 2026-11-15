#pragma once
#include "WiFi.h"
struct Datagram { IPAddress ip; uint16_t port; std::vector<uint8_t> bytes; };
struct WiFiUDP {
    std::deque<Datagram> incoming;
    std::vector<Datagram> sent;
    Datagram active{}, outgoing{};
    bool bound=false;
    size_t offset=0;
    int begin(uint16_t port) { bound=(port==5009); return bound ? 1 : 0; }
    void stop() { bound=false; }
    int parsePacket() {
        if (incoming.empty()) return 0;
        active=incoming.front(); incoming.pop_front(); offset=0;
        return static_cast<int>(active.bytes.size());
    }
    IPAddress remoteIP() const { return active.ip; }
    uint16_t remotePort() const { return active.port; }
    int read(uint8_t* dest, size_t size) {
        size_t left=active.bytes.size()-offset;
        size_t count=(left<size ? left:size);
        std::memcpy(dest,active.bytes.data()+offset,count); offset+=count;
        return static_cast<int>(count);
    }
    void flush() { offset=active.bytes.size(); }
    int beginPacket(IPAddress ip,uint16_t port) { outgoing={ip,port,{}}; return 1; }
    size_t write(const uint8_t* data,size_t size) {
        outgoing.bytes.insert(outgoing.bytes.end(),data,data+size); return size;
    }
    int endPacket() { sent.push_back(outgoing); return 1; }
};
