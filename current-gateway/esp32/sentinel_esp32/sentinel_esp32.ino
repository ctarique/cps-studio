#include <Arduino.h>
#include <WiFi.h>
#include <Network.h>
#include <mbedtls/md.h>
#include <mbedtls/sha256.h>
#include <esp_system.h>
#include <lwip/sockets.h>
#include "experiment.h"
#include "response.h"
#if __has_include("sentinel_config.local.h")
#include "sentinel_config.local.h"
#else
#include "sentinel_config.example.h"
#endif

NetworkServer server(80);
NetworkClient peer;
IPAddress gatewayIP;
scps::Engine engine;
char bootID[33]={},runID[33]="00000000000000000000000000000000";
char programHash[65]="0000000000000000000000000000000000000000000000000000000000000000";
uint8_t key[32];
uint32_t sequence=1,clientStarted=0,reconnectAt=0;
bool configured=false,listening=false,parsedHeaders=false;
char headerBuf[1537],bodyBuf[513],signature[65],target[100],method[5];
size_t headerUsed=0,bodyUsed=0,bodyLength=0;

void toHex(const uint8_t* in,size_t n,char* out) {
  static const char* alphabet="0123456789abcdef";
  for(size_t i=0;i<n;i++){out[2*i]=alphabet[in[i]>>4];out[2*i+1]=alphabet[in[i]&15];}
  out[n*2]=0;
}
void hashText(const char* data,char* result) {
  uint8_t raw[32];mbedtls_sha256((const unsigned char*)data,strlen(data),raw,0);toHex(raw,32,result);
}
void mac(const String& context,const char* data,char* result) {
  mbedtls_md_context_t ctx;mbedtls_md_init(&ctx);
  const mbedtls_md_info_t* info=mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  uint8_t raw[32]={};
  if(mbedtls_md_setup(&ctx,info,1)!=0){result[0]=0;return;}
  mbedtls_md_hmac_starts(&ctx,key,32);
  mbedtls_md_hmac_update(&ctx,(const unsigned char*)context.c_str(),context.length());
  mbedtls_md_hmac_update(&ctx,(const unsigned char*)data,strlen(data));
  mbedtls_md_hmac_finish(&ctx,raw);mbedtls_md_free(&ctx);toHex(raw,32,result);
}
bool equalSignature(const char* expected,const char* supplied) {
  if(!scps::hex(expected,64)||!scps::hex(supplied,64))return false;
  uint8_t diff=0;for(int i=0;i<64;i++)diff|=expected[i]^supplied[i];return diff==0;
}
void ledOutput() {
  if(engine.enabled)digitalWrite(SENTINEL_LED_PIN,engine.led==SENTINEL_LED_ACTIVE_HIGH?HIGH:LOW);
}
void closePeer() {
  peer.stop();headerUsed=bodyUsed=bodyLength=0;parsedHeaders=false;
}
void sendResponse(const char* response,int length) {
  if(length>0)scps::sendOnce(response,size_t(length),[](const char* bytes,size_t n) {
    return send(peer.fd(),bytes,n,MSG_DONTWAIT);
  });
  closePeer();
}
void reject(int code=400) {
  char response[scps::RESPONSE_CAPACITY];
  int length=snprintf(response,sizeof(response),"HTTP/1.1 %d Rejected\r\nConnection: close\r\nContent-Length: 0\r\n\r\n",code);
  sendResponse(response,length);
}
void reply(const String& context) {
  engine.tick(millis());ledOutput();
  char result[385],signedResult[65];
  snprintf(result,sizeof(result),"SCPS1|%s|%lu|%s|%s|%d|%d|%s|DEVICE",
           bootID,(unsigned long)sequence,runID,engine.state,engine.led?1:0,engine.enabled?1:0,programHash);
  mac(context,result,signedResult);
  if(!signedResult[0]){reject(503);return;}
  char response[scps::RESPONSE_CAPACITY];
  int length=snprintf(response,sizeof(response),"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nCache-Control: no-store\r\nConnection: close\r\nContent-Length: %u\r\nX-Sentinel-Signature: %s\r\n\r\n%s",
                      unsigned(strlen(result)),signedResult,result);
  sendResponse(response,length);
}
bool parseHeaders() {
  headerBuf[headerUsed]=0;
  char* line=strstr(headerBuf,"\r\n");if(!line)return false;*line=0;
  char protocol[12],extra[2];
  if(sscanf(headerBuf,"%4s %99s %11s %1s",method,target,protocol,extra)!=3||strcmp(protocol,"HTTP/1.1"))return false;
  bool hasLength=false,hasSignature=false;signature[0]=0;
  char* p=line+2;int count=0;
  while(*p) {
    char* end=strstr(p,"\r\n");if(!end)return false;*end=0;
    if(!*p)break;
    if(++count>16)return false;
    char* colon=strchr(p,':');if(!colon)return false;*colon=0;
    for(char* k=p;*k;k++) {if(*k>='A'&&*k<='Z')*k+=32;}
    char* value=colon+1;while(*value==' ')value++;
    if(!strcmp(p,"content-length")) {
      uint32_t n=0;if(hasLength||!scps::number(value,n,512))return false;
      hasLength=true;bodyLength=n;
    } else if(!strcmp(p,"x-sentinel-signature")) {
      if(hasSignature||!scps::hex(value,64))return false;hasSignature=true;strcpy(signature,value);
    } else if(!strcmp(p,"transfer-encoding")||!strcmp(p,"expect"))return false;
    p=end+2;
  }
  if(!strcmp(method,"GET"))return !hasSignature&&bodyLength==0;
  return !strcmp(method,"POST")&&hasLength&&bodyLength>0&&hasSignature;
}
void dispatch() {
  bodyBuf[bodyUsed]=0;
  if(!strcmp(method,"GET")) {
    if(!strcmp(target,"/health")) {
      const char* diagnostic="{\"service\":\"Sentinel-CPS\",\"protocol\":1,\"diagnostic_only\":true}";
      char response[scps::RESPONSE_CAPACITY];
      int length=snprintf(response,sizeof(response),"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nCache-Control: no-store\r\nConnection: close\r\nContent-Length: %u\r\n\r\n%s",unsigned(strlen(diagnostic)),diagnostic);
      sendResponse(response,length);return;
    }
    const char* prefix="/v1/status?nonce=";
    if(strncmp(target,prefix,strlen(prefix))||!scps::hex(target+strlen(prefix),32)){reject(404);return;}
    reply(String("STATUS\n")+String(target+strlen(prefix))+"\n");return;
  }
  if(strcmp(target,"/v1/work")){reject(404);return;}
  char expected[65],requestHash[65];mac("POST\n/v1/work\n",bodyBuf,expected);
  if(!equalSignature(expected,signature)){reject(403);return;}
  hashText(bodyBuf,requestHash);
  char* fields[6];fields[0]=bodyBuf;int count=1;
  for(char* p=bodyBuf;*p;p++)if(*p=='|'){*p=0;if(count==6){reject();return;}fields[count++]=p+1;}
  if(count!=6||strcmp(fields[0],"SCPS1")||strcmp(fields[1],bootID)||!scps::hex(fields[3],32)){reject(409);return;}
  uint32_t seq=0;
  if(!scps::number(fields[2],seq,99999998)||seq!=sequence){reject(409);return;}
  const char* action=fields[4];const char* program=fields[5];bool accepted=false;
  if(!strcmp(action,"RUN")) {
    accepted=engine.start(program,millis());if(accepted)hashText(program,programHash);
  } else if(!*program&&!strcmp(action,"STOP")) {engine.stop();accepted=true;}
  else if(!*program&&!strcmp(action,"RESET")) {engine.stop(true);memset(programHash,'0',64);programHash[64]=0;accepted=true;}
  if(!accepted){reject(409);return;}
  strcpy(runID,fields[3]);sequence++;ledOutput();
  reply(String("RESULT\n")+requestHash+"\n");
}
void pollClient() {
  if(!peer) {
    peer=server.accept();
    if(!peer)return;
    if(peer.remoteIP()!=gatewayIP){closePeer();return;}
    peer.setTimeout(50);clientStarted=millis();headerUsed=bodyUsed=bodyLength=0;parsedHeaders=false;
  }
  if(uint32_t(millis()-clientStarted)>1000){closePeer();return;}
  int budget=256;
  while(peer.available()&&budget-->0) {
    int value=peer.read();if(value<0)break;
    if(!parsedHeaders) {
      if(headerUsed==1536||value==0||value>126||(value<32&&value!='\r'&&value!='\n')){reject();return;}
      headerBuf[headerUsed++]=char(value);
      if(headerUsed>=4&&!memcmp(headerBuf+headerUsed-4,"\r\n\r\n",4)) {
        if(!parseHeaders()){reject();return;}parsedHeaders=true;
        if(bodyLength==0){dispatch();return;}
      }
    } else {
      if(bodyUsed==512||value<32||value>126){reject();return;}
      bodyBuf[bodyUsed++]=char(value);
      if(bodyUsed==bodyLength){dispatch();return;}
    }
  }
}
bool configurationValid() {
  if(strlen(SENTINEL_WIFI_SSID)<1||strlen(SENTINEL_WIFI_SSID)>32||
     strlen(SENTINEL_WIFI_PASSWORD)<8||strlen(SENTINEL_WIFI_PASSWORD)>63||
     !gatewayIP.fromString(SENTINEL_GATEWAY_IP)||!scps::hex(SENTINEL_DEVICE_KEY,64))return false;
  if(!(gatewayIP[0]==10||(gatewayIP[0]==172&&gatewayIP[1]>=16&&gatewayIP[1]<=31)||
       (gatewayIP[0]==192&&gatewayIP[1]==168)))return false;
  // Classic ESP32 output-capable pins only. Instructor must confirm the specific LED mapping.
  const int pin=SENTINEL_LED_PIN;
  if(pin!=-1&&pin!=2&&pin!=4&&pin!=12&&pin!=13&&pin!=14&&pin!=15&&pin!=25&&pin!=26&&pin!=27&&pin!=32&&pin!=33)return false;
  for(int i=0;i<32;i++) {
    char pair[3]={SENTINEL_DEVICE_KEY[i*2],SENTINEL_DEVICE_KEY[i*2+1],0};key[i]=strtoul(pair,nullptr,16);
  }
  engine.enabled=pin!=-1;return true;
}
void setup() {
  Serial.begin(115200); // Instructor diagnostic output only; no serial command reader.
  configured=configurationValid();
  if(!configured){Serial.println("CONFIGURATION_REQUIRED; no network or GPIO started");return;}
  if(engine.enabled){pinMode(SENTINEL_LED_PIN,OUTPUT);ledOutput();}
  WiFi.mode(WIFI_STA);uint8_t randomBoot[16];esp_fill_random(randomBoot,sizeof(randomBoot));toHex(randomBoot,16,bootID);
  WiFi.setAutoReconnect(true);WiFi.begin(SENTINEL_WIFI_SSID,SENTINEL_WIFI_PASSWORD);
  Serial.println("Wi-Fi connection requested; physical validation pending");
}
void loop() {
  if(!configured){delay(10);return;}
  engine.tick(millis());ledOutput();
  if(WiFi.status()!=WL_CONNECTED) {
    engine.stop();ledOutput();
    if(listening){closePeer();server.end();listening=false;}
    delay(1);return;
  }
  if(!listening){server.begin();listening=true;Serial.println("Bounded Wi-Fi service available");}
  pollClient();delay(1);
}
