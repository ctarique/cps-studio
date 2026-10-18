#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>

namespace scps {
struct Op { char kind; uint16_t value; };
inline bool hex(const char* text, size_t n) {
  if (strlen(text)!=n) return false;
  for (size_t i=0;i<n;i++) if (!((text[i]>='0'&&text[i]<='9')||(text[i]>='a'&&text[i]<='f'))) return false;
  return true;
}
inline bool number(const char* s, uint32_t& value, uint32_t max) {
  if (!*s || (*s=='0' && s[1])) return false;
  uint32_t v=0;
  for (;*s;s++) {
    if (*s<'0'||*s>'9'||v>(max-uint32_t(*s-'0'))/10) return false;
    v=v*10+(*s-'0');
    if (v>max) return false;
  }
  value=v;return true;
}
inline bool parse(const char* text, Op* ops, size_t& count, bool gpio) {
  count=0;uint32_t total=0;int lastLed=-1;
  if (!*text || strlen(text)>255) return false;
  const char* p=text;
  while (*p) {
    const char* end=strchr(p,',');size_t n=end?size_t(end-p):strlen(p);
    if (count==32 || n<2 || n>5) return false;
    char arg[6]={};memcpy(arg,p+1,n-1);uint32_t value=0;
    if (!number(arg,value,1000)) return false;
    if (*p=='L') { if (!gpio||value>1) return false;lastLed=int(value); }
    else if (*p=='W') { if (value<10 || value>1000) return false;total+=value; }
    else if (*p=='S') { if(value!=0) return false; }
    else return false;
    if(total>5000) return false;
    ops[count++]={*p,uint16_t(value)};
    if(!end) break;
    p=end+1;if(!*p) return false;
  }
  return count>0 && lastLed!=1;
}
struct Engine {
  Op ops[32];size_t count=0,pos=0;
  bool enabled=false,led=false,running=false;
  uint32_t due=0,started=0;
  const char* state="IDLE";
  bool start(const char* text,uint32_t now) {
    if(running) return false;
    Op candidate[32];size_t length=0;
    if(!parse(text,candidate,length,enabled))return false;
    memcpy(ops,candidate,length*sizeof(Op));count=length;pos=0;due=now;started=now;
    state="RUNNING";running=true;led=false;return true;
  }
  void stop(bool reset=false) { running=false;led=false;count=0;state=reset?"IDLE":"STOPPED"; }
  void tick(uint32_t now) {
    if(!running)return;
    // Bounded execution even if the network client stalls. Unsigned clock wrap is intentional.
    if(uint32_t(now-started)>5500) {stop();return;}
    if(int32_t(now-due)<0)return;
    while(pos<count) {
      Op op=ops[pos++];
      if(op.kind=='L')led=op.value!=0;
      else if(op.kind=='W') {due=now+op.value;return;}
    }
    running=false;led=false;state="COMPLETE";
  }
};
}
