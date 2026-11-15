#pragma once
#include "Arduino.h"
#define AF_INET 2
#define SOCK_DGRAM 2
#define IPPROTO_UDP 17
#define INADDR_ANY 0
#define MSG_DONTWAIT 64
using socklen_t = unsigned;
struct in_addr { uint32_t s_addr; };
struct sockaddr { uint16_t sa_family; char data[14]; };
struct sockaddr_in { uint16_t sin_family; uint16_t sin_port; in_addr sin_addr; char pad[8]; };
inline uint16_t htons(uint16_t v) { return static_cast<uint16_t>((v<<8)|(v>>8)); }
inline uint32_t htonl(uint32_t v) { return ((v&255)<<24)|((v&65280)<<8)|((v>>8)&65280)|(v>>24); }
namespace fake {
struct Datagram { std::vector<uint8_t> bytes; uint32_t ip; uint16_t port; };
inline std::deque<Datagram> replies;
inline std::vector<std::vector<uint8_t>> sent;
inline uint16_t boundPort=0, sentPort=0;
inline uint32_t sentIp=0;
inline int sockets=0, closes=0, receives=0;
inline int sendResult=660, receiveError=0;
inline int closeResult=0;
inline void (*duringReceive)() = nullptr;
inline bool nonblocking=false;
}
inline int socket(int domain, int type, int protocol) { ++fake::sockets; return domain==AF_INET && type==SOCK_DGRAM && protocol==IPPROTO_UDP && fake::ok()?10:-1; }
inline int bind(int, const sockaddr *s, socklen_t) { fake::boundPort=reinterpret_cast<const sockaddr_in *>(s)->sin_port; return fake::ok()?0:-1; }
inline int close(int) { ++fake::closes; fake::replies.clear(); return fake::closeResult; }
inline int sendto(int, const void *p, size_t n, int flags, const sockaddr *s, socklen_t) {
 const auto *v=static_cast<const uint8_t *>(p); const auto *dest=reinterpret_cast<const sockaddr_in *>(s);
 fake::sentIp=dest->sin_addr.s_addr; fake::sentPort=dest->sin_port;
 if (flags!=MSG_DONTWAIT) return -1;
 if (fake::sendResult==static_cast<int>(n)) fake::sent.emplace_back(v,v+n);
 return fake::sendResult;
}
inline int recvfrom(int, void *p, size_t n, int flags, sockaddr *s, socklen_t *size) {
 ++fake::receives;
 if (flags!=MSG_DONTWAIT) { errno=EINVAL; return -1; }
 if (fake::receiveError) { errno=fake::receiveError; return -1; }
 if (fake::replies.empty()) { errno=EWOULDBLOCK; return -1; }
 auto r=fake::replies.front(); fake::replies.pop_front();
 auto *peer=reinterpret_cast<sockaddr_in *>(s); peer->sin_family=AF_INET; peer->sin_port=htons(r.port); peer->sin_addr.s_addr=r.ip; *size=sizeof(*peer);
 const size_t copy=std::min(n,r.bytes.size()); std::memcpy(p,r.bytes.data(),copy);
 if(fake::duringReceive) { auto hook=fake::duringReceive; fake::duringReceive=nullptr; hook(); }
 return static_cast<int>(copy);
}
