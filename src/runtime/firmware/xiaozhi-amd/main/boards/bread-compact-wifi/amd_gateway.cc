#include "amd_gateway.h"
#include "amd_bridge.h"
#include "esp_http_server.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "settings.h"
#include "wifi_manager.h"
#include "mcp_server.h"
#include "application.h"
#include "board.h"
#include "display/display.h"
#include "audio/audio_codec.h"
#include "assets/lang_config.h"
#include "driver/usb_serial_jtag.h"
#include <map>
#include <deque>
#include <bitset>
#include <string>

namespace {
std::string code, token;
int64_t pair_after=0;
struct Retry { std::string payload, reply; };
std::map<std::string,Retry> retries;
std::deque<std::string> retry_order;
std::bitset<32768> submitted_ids;
SemaphoreHandle_t local_lock=nullptr;
std::map<std::string,std::string> local_results;
std::string localCommand(const std::string& action,cJSON* p) {
 if(action=="audio.status") return "{\"status\":\"success\",\"data\":{\"volume\":"+std::to_string(Board::GetInstance().GetAudioCodec()->output_volume())+"}}";
 int volume=0;
 if(action=="audio.config") { auto v=cJSON_GetObjectItem(p,"volume");if(!cJSON_IsNumber(v)||v->valuedouble<0||v->valuedouble>100||v->valuedouble!=(int)v->valuedouble) return "{\"status\":\"invalid_volume\"}";volume=v->valueint; }
 char b[40];snprintf(b,sizeof(b),"local-%08lx",(unsigned long)esp_random());std::string id=b;
 xSemaphoreTake(local_lock,portMAX_DELAY);
 if(local_results.size()>=16) {auto old=local_results.begin();while(old!=local_results.end()&&old->second=="{\"status\":\"pending\"}")++old;if(old==local_results.end()){xSemaphoreGive(local_lock);return "{\"status\":\"busy\"}";}local_results.erase(old);}
 local_results[id]="{\"status\":\"pending\"}";xSemaphoreGive(local_lock);
 Application::GetInstance().Schedule([id,action,volume]() {
  if(action=="audio.config") Board::GetInstance().GetAudioCodec()->SetOutputVolume(volume);
  else Application::GetInstance().PlaySound(Lang::Sounds::OGG_POPUP);
  xSemaphoreTake(local_lock,portMAX_DELAY);
  local_results[id]=action=="audio.config"?"{\"status\":\"success\",\"data\":{\"volume\":"+std::to_string(volume)+"}}":"{\"status\":\"success\",\"data\":{\"playback_requested\":true,\"audible_verified\":false}}";
  xSemaphoreGive(local_lock);
 });
 return "{\"status\":\"pending\",\"request_id\":\""+id+"\"}";
}
std::string dump(cJSON* j) { char* p=cJSON_PrintUnformatted(j); std::string s=p?p:"{}"; cJSON_free(p); cJSON_Delete(j); return s; }
esp_err_t reply(httpd_req_t* r,const std::string& s,const char* status="200 OK") {
 httpd_resp_set_status(r,status); httpd_resp_set_type(r,"application/json");
 httpd_resp_set_hdr(r,"Cache-Control","no-store"); return httpd_resp_send(r,s.data(),s.size());
}
std::string field(cJSON* j,const char* key) { auto v=cJSON_GetObjectItem(j,key); return cJSON_IsString(v)?v->valuestring:""; }
bool boundedJson(const std::string& s) {
 int depth=0;bool quoted=false,escaped=false;
 for(char ch:s) { if(quoted){if(escaped)escaped=false;else if(ch=='\\')escaped=true;else if(ch=='"')quoted=false;continue;}
  if(ch=='"')quoted=true;else if(ch=='{'||ch=='['){if(++depth>12)return false;}else if(ch=='}'||ch==']'){if(--depth<0)return false;}
 }return !quoted&&depth==0;
}
esp_err_t handle(httpd_req_t* r) {
 std::string path=r->uri;
 if(path=="/api/info" && r->method==HTTP_GET) return reply(r,std::string("{\"gateway\":\"ESP32-S3\",\"api_version\":1,\"transport\":\"usb_serial_jtag\",\"usb_connected\":")+(usb_serial_jtag_is_connected()?"true}":"false}"));
 // Native clients do not require cross-origin browser access.
 if(httpd_req_get_hdr_value_len(r,"Origin")) return reply(r,"{\"error\":\"browser_origin_denied\"}","403 Forbidden");
 if(r->content_len>2048) return reply(r,"{\"error\":\"body_too_large\"}","413 Content Too Large");
 std::string body(r->content_len,'\0'); size_t got=0;
 while(got<body.size()) { int n=httpd_req_recv(r,&body[got],body.size()-got); if(n<=0) return ESP_FAIL; got+=n; }
 if(!boundedJson(body))return reply(r,"{\"error\":\"invalid_or_deep_json\"}","400 Bad Request");
 if(path=="/api/pair" && r->method==HTTP_POST) {
  auto now=esp_timer_get_time(); if(now<pair_after) return reply(r,"{\"error\":\"retry_later\"}","429 Too Many Requests");
  pair_after=now+2000000; auto j=cJSON_Parse(body.c_str()); bool ok=field(j,"code")==code; cJSON_Delete(j);
  if(!ok) return reply(r,"{\"error\":\"invalid_pair_code\"}","403 Forbidden");
  auto out=cJSON_CreateObject(); cJSON_AddStringToObject(out,"token",token.c_str()); return reply(r,dump(out));
 }
 char auth[160]={}; httpd_req_get_hdr_value_str(r,"Authorization",auth,sizeof(auth));
 if(std::string(auth)!="Bearer "+token) return reply(r,"{\"error\":\"unauthorized\"}","401 Unauthorized");
 if(path=="/api/events" && r->method==HTTP_GET) return reply(r,AmdBridge::Instance().GatewayEvent());
 if(path.rfind("/api/results/",0)==0 && r->method==HTTP_GET) {
  auto id=path.substr(13);
  if(id.rfind("local-",0)==0) { xSemaphoreTake(local_lock,portMAX_DELAY);auto it=local_results.find(id);std::string value=it==local_results.end()?"{\"status\":\"unknown_or_expired\"}":it->second;xSemaphoreGive(local_lock);return reply(r,value); }
  return reply(r,AmdBridge::Instance().GatewayResult(id));
 }
 if(path=="/api/commands" && r->method==HTTP_POST) {
  auto j=cJSON_Parse(body.c_str()); auto id=field(j,"client_id"),action=field(j,"action"); auto p=cJSON_GetObjectItem(j,"params");
  if(id.empty() || id.size()>64 || !cJSON_IsObject(p)) { cJSON_Delete(j); return reply(r,"{\"error\":\"invalid_request\"}","400 Bad Request"); }
  auto old=retries.find(id);
  if(old!=retries.end()) { cJSON_Delete(j); return old->second.payload==body?reply(r,old->second.reply):reply(r,"{\"error\":\"id_conflict\"}","409 Conflict"); }
  // Retired IDs remain in a bounded Bloom filter: a retry can be rejected,
  // but can never silently execute again after its cached response is evicted.
  uint32_t hash=2166136261u; for(unsigned char ch:id) hash=(hash^ch)*16777619u;
  auto a=hash%32768, b=((hash>>16)^(hash*0x9e3779b9u))%32768;
  if(submitted_ids[a]&&submitted_ids[b]) { cJSON_Delete(j); return reply(r,"{\"error\":\"retired_client_id_query_result_instead\"}","409 Conflict"); }
  submitted_ids.set(a);submitted_ids.set(b);
  if(retries.size()>=128) { retries.erase(retry_order.front());retry_order.pop_front(); }
  std::string result;
  if(action=="audio.status"||action=="audio.config"||action=="notify.test")result=localCommand(action,p);
  else result=AmdBridge::Instance().GatewaySubmit(action,dump(cJSON_Duplicate(p,true)));
  cJSON_Delete(j);retries[id]={body,result};retry_order.push_back(id); return reply(r,result);
 }
 return reply(r,"{\"error\":\"not_found\"}","404 Not Found");
}
void showCode() { Board::GetInstance().GetDisplay()->ShowPairingCode(code); }
}
void StartAmdGateway() {
 static bool started=false; if(started) return; started=true;
 local_lock=xSemaphoreCreateMutex();if(!local_lock)return;
 Settings settings("amd_gateway",true); code=settings.GetString("pair_code"); token=settings.GetString("token");
 if(code.empty()) { char b[8]; snprintf(b,sizeof(b),"%06lu",(unsigned long)(esp_random()%1000000)); code=b; settings.SetString("pair_code",code); }
 if(token.empty()) { for(int i=0;i<8;i++){char b[9];snprintf(b,sizeof(b),"%08lx",(unsigned long)esp_random());token+=b;} settings.SetString("token",token); }
 McpServer::GetInstance().AddTool("self.desk.app_pairing","用户询问上位机配对码、要求播报或显示配对码时调用。返回真实六位码，请逐位清晰朗读，包含开头的零；不要只让用户看屏幕。",PropertyList(),[](const PropertyList&)->ReturnValue {
  Application::GetInstance().Schedule(showCode);
  std::string spoken;
  for (char digit : code) { if (!spoken.empty()) spoken += "，"; spoken += digit; }
  return std::string("本机当前上位机配对码是：") + spoken + "。请逐位朗读给用户，保留所有六位数字及前导零。不要朗读为整数，不要编造或更换数字。";
 });
 httpd_config_t cfg=HTTPD_DEFAULT_CONFIG(); cfg.server_port=8080; cfg.stack_size=8192; cfg.uri_match_fn=httpd_uri_match_wildcard;
 httpd_handle_t server=nullptr; if(httpd_start(&server,&cfg)!=ESP_OK) return;
 httpd_uri_t get{};get.uri="/api/*";get.method=HTTP_GET;get.handler=handle;httpd_register_uri_handler(server,&get);
 httpd_uri_t post=get;post.method=HTTP_POST;httpd_register_uri_handler(server,&post);
}
