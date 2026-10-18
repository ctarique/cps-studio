#include "../esp32/sentinel_esp32/experiment.h"
#include "../esp32/sentinel_esp32/response.h"
#include <assert.h>
#include <stdio.h>
#include <string>
int main(){
  scps::Engine e;e.enabled=true;
  assert(e.start("L1,W100,L0,S0",100));e.tick(100);assert(e.led&&e.running);
  assert(!e.start("S0",110));e.tick(199);assert(e.led);e.tick(200);assert(!e.led&&!e.running);
  assert(std::string(e.state)=="COMPLETE");
  const char* bad[]={"","L2","L1","W0","W9","W1001","S1","L0,","L0,,S0","W010","W-1","W99999999999999999","W1000,W1000,W1000,W1000,W1000,W1000","L0|S0"};
  for(auto s:bad){scps::Op ops[32];size_t n;assert(!scps::parse(s,ops,n,true));}
  std::string many="S0";for(int i=0;i<32;i++)many+=",S0";scps::Op ops[32];size_t n;assert(!scps::parse(many.c_str(),ops,n,true));
  assert(!scps::parse("L0",ops,n,false));assert(scps::parse("S0,W10",ops,n,false));
  assert(e.start("L1,W1000,L0",0xfffffff0));e.tick(0xfffffff0);assert(e.led);
  e.tick(uint32_t(0xfffffff0+1000));assert(!e.led);
  assert(e.start("L1,W1000,L0",0));e.tick(0);e.tick(5501);assert(!e.running&&!e.led);
  assert(e.start("L1,W100,L0",0));e.tick(0);e.stop();assert(!e.led&&!e.running);
  e.stop(true);assert(std::string(e.state)=="IDLE");
  uint32_t v;assert(!scps::number("01",v,512));assert(!scps::number("999999999999",v,512));assert(scps::number("512",v,512));
  assert(scps::hex("0123456789abcdef0123456789abcdef",32));assert(!scps::hex("ABC",3));
  const char response[]="HTTP/1.1 200 OK";int calls=0;
  auto full=[&](const char* data,size_t size){calls++;assert(data==response);return int(size);};
  assert(scps::sendOnce(response,strlen(response),full));assert(calls==1);
  calls=0;assert(!scps::sendOnce(response,strlen(response),[&](const char*,size_t size){calls++;return int(size)-1;}));assert(calls==1);
  calls=0;assert(!scps::sendOnce(response,strlen(response),[&](const char*,size_t){calls++;return -1;}));assert(calls==1);
  calls=0;assert(!scps::sendOnce(response,0,full));assert(!scps::sendOnce(response,scps::RESPONSE_CAPACITY,full));assert(calls==0);
  puts("PASS: firmware parser, limits, disabled GPIO, stop/reset, deadline, clock-wrap, and single-send response checks");
}
