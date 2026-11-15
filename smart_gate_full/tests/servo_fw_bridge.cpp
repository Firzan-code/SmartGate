#define main servo_host_unused_main
#include "servo_fw_sketch_test.cpp"
#undef main
void emit() {
    for(const auto& packet:sUdp.sent) {
        std::cout<<"WIRE ";for(auto x:packet.bytes)std::printf("%02x",x);std::cout<<"\n";
    }
    sUdp.sent.clear();
    std::cout<<"STATE "<<sState<<" WRITES "<<write_calls<<"\nEND\n"<<std::flush;
}
int main() {
    boot();emit();std::string kind,hex;uint32_t when;
    while(std::cin>>kind>>when) {
        fake_now=when;
        if(kind=="RX") {
            std::cin>>hex;std::vector<uint8_t> data;
            for(size_t i=0;i+1<hex.size();i+=2)data.push_back(static_cast<uint8_t>(std::stoul(hex.substr(i,2),nullptr,16)));
            sUdp.incoming.push_back({IPAddress(192,0,2,20),5010,data});
        }
        loop();emit();
    }
    return 0;
}
