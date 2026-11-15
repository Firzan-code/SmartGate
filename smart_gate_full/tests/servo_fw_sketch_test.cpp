#include "Arduino.h"
#include "WiFiUdp.h"
#include <stdexcept>
#include <iostream>
#include <functional>
#include <map>
uint32_t fake_now=0;
int attach_calls=0,write_calls=0,detach_calls=0,last_pin=-1;
uint32_t last_duty=0;
bool attach_ok=true,write_ok=true;
SerialMock Serial;
WiFiMock WiFi;
#include "demo_servo_esp32s3.ino"
void check(bool value,const char* message) { if(!value) throw std::runtime_error(message); }
void boot() { setup(); loop(); }
void step(uint32_t ms) { fake_now=ms; loop(); }
void inject(uint32_t action,uint32_t boot_id=0,uint32_t nonce=0,
            IPAddress source=IPAddress(192,0,2,20),uint16_t port=5010,int extra=0) {
    uint8_t bytes[16]; packServo(bytes,"SGC1",boot_id?boot_id:sBoot,nonce?nonce:sNonce,action);
    std::vector<uint8_t> data(bytes,bytes+16);
    if(extra>0) data.insert(data.end(),extra,0x42);
    if(extra<0) data.resize(15);
    sUdp.incoming.push_back({source,port,data});
    loop();
}
void armed() { boot(); check(sState==0,"boot idle"); inject(1); check(sState==1,"arm accepted"); }
int main(int argc,char** argv) {
    std::map<std::string,std::function<void()>> tests={
        {"boot_no_pwm",[]{boot();check(attach_calls==0&&write_calls==0,"boot must not attach/write");check(sState==0,"idle");}},
        {"empty_config_inert",[]{boot();check(!sConfigured&&WiFi.begin_calls==0&&!sUdp.bound,"empty must remain inert");check(attach_calls==0,"empty no pwm");}},
        {"arm_open_once",[]{armed();check(attach_calls==1&&write_calls==1&&last_pin==42,"arm target90");auto duty90=last_duty;inject(1);check(write_calls==1,"duplicate arm no write");inject(2);check(sState==2&&write_calls==2&&last_duty>duty90,"open target110");inject(2);inject(1);check(write_calls==2,"no duplicate movement");}},
        {"open_without_arm_rejected",[]{boot();inject(2);check(sState==0&&write_calls==0,"open requires arm");}},
        {"source_and_length_rejected",[]{boot();inject(1,0,0,IPAddress(192,0,2,99));inject(1,0,0,IPAddress(192,0,2,20),5011);inject(1,0,0,IPAddress(192,0,2,20),5010,1);inject(1,0,0,IPAddress(192,0,2,20),5010,-1);check(sState==0&&attach_calls==0,"reject invalid packets");inject(1);check(sState==1,"valid after oversized works");}},
        {"old_boot_nonce_rejected",[]{boot();inject(1,sBoot+1,sNonce);inject(1,sBoot,sNonce+77);check(attach_calls==0,"reject wrong boot/nonce");auto old=sNonce;step(500);check(sNonce!=old,"nonce rotates");inject(1,sBoot,old);check(attach_calls==0,"old nonce rejected");inject(1);check(sState==1,"fresh nonce accepted");}},
        {"stale_nonce_rejected",[]{armed();fake_now=800;uint8_t bytes[16];packServo(bytes,"SGC1",sBoot,sNonce,2);sUdp.incoming.push_back({IPAddress(192,0,2,20),5010,{bytes,bytes+16}});receiveServo();check(write_calls==1,"expired nonce cannot move");}},
        {"watchdog_latches_detach",[]{armed();step(sLastCommand+2001);check(sState==4&&detach_calls==1&&write_calls==1,"timeout detaches without close");inject(1);inject(2);check(attach_calls==1&&write_calls==1,"no auto rearm after watchdog");}},
        {"watchdog_precedes_late_keepalive",[]{armed();fake_now=sLastCommand+2001;inject(4);check(sState==4&&detach_calls==1,"late packet cannot rescue expired session");}},
        {"keepalive_no_movement",[]{armed();for(uint32_t t=200;t<=3000;t+=200){step(t);inject(4);}check(sState==1&&write_calls==1&&detach_calls==0,"keepalive holds without write");}},
        {"disarm_no_close",[]{armed();inject(2);inject(3);check(sState==4&&detach_calls==1&&write_calls==2,"disarm detach only");inject(1);inject(2);check(write_calls==2,"disarmed terminal");}},
        {"attach_failure_latches",[]{boot();attach_ok=false;inject(1);check(sState==3&&write_calls==0,"attach failure terminal");inject(1);check(attach_calls==1,"no retry attach error");}},
        {"write_failure_detaches",[]{boot();write_ok=false;inject(1);check(sState==3&&detach_calls==1,"write failure detaches");}},
        {"wifi_loss_detaches",[]{armed();WiFi.status_value=0;step(100);check(sState==4&&detach_calls==1,"wifi loss detach");WiFi.status_value=WL_CONNECTED;step(200);inject(1);check(write_calls==1,"no rearm reconnect");}},
        {"millis_rollover",[]{fake_now=0xffffff00u;armed();step(0x200);inject(4);check(sState==1,"rollover not false timeout");step(0xa00);check(sState==4,"rollover real timeout");}},
        {"protocol_bytes",[]{uint8_t b[16];packServo(b,"SGH1",0x12345678,0x90abcdef,1);std::cout<<"WIRE ";for(auto x:b) std::printf("%02x",x);std::cout<<"\n";check(b[4]==0x78&&b[7]==0x12&&b[15]==0,"little endian exact");}}
    };
    if(argc==2&&std::string(argv[1])=="--list"){for(auto& item:tests)std::cout<<item.first<<"\n";return 0;}
    try {check(argc==2,"choose case");tests.at(argv[1])();std::cout<<"PASS "<<argv[1]<<"\n";return 0;}
    catch(const std::exception& e){std::cerr<<"FAIL "<<(argc>1?argv[1]:"")<<": "<<e.what()<<"\n";return 1;}
}
