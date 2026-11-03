#include "amd_bridge.h"
#include "mcp_server.h"
#include "application.h"
#include "assets/lang_config.h"
#include "driver/usb_serial_jtag.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "esp_log.h"
#include <cstdio>
#include <algorithm>

static std::string Dump(cJSON* json) {
    char* value = cJSON_PrintUnformatted(json);
    std::string out = value ? value : "{}";
    cJSON_free(value); cJSON_Delete(json); return out;
}

std::string AmdBridge::GatewayResult(const std::string& id) {
    if (!lock_) return "{\"status\":\"unavailable\"}";
    Tick(); xSemaphoreTake(lock_, portMAX_DELAY);
    auto it=results_.find(id); auto value=it==results_.end()?std::string("{\"status\":\"unknown_or_expired\"}"):it->second;
    xSemaphoreGive(lock_); return value;
}
std::string AmdBridge::GatewayEvent() {
    if (!lock_) return "{}";
    xSemaphoreTake(lock_,portMAX_DELAY); auto value=last_event_; xSemaphoreGive(lock_); return value;
}

void AmdBridge::Start() {
    lock_ = xSemaphoreCreateMutex();
    if (!lock_) return;
    usb_serial_jtag_driver_config_t cfg{};
    cfg.tx_buffer_size = 4096; cfg.rx_buffer_size = 4096;
    if (usb_serial_jtag_driver_install(&cfg) != ESP_OK) return;
    ready_ = xTaskCreate(ReceiveTask, "amd_usb", 6144, this, 5, nullptr) == pdPASS;
    ESP_LOGI("AmdBridge", "USB business transport ready=%d; logs remain on UART0", ready_);
    auto& server = McpServer::GetInstance();
    server.AddTool("self.desk.calibrate_lights", "重新标定书架灯带。仅在用户要求标定时调用；过程约90秒，要求摄像头和灯带保持不动。返回pending只表示已提交，必须用self.desk.result查询最终结果；completed=true才表示标定完成。", PropertyList(),
        [this](const PropertyList&)->ReturnValue { return Submit("light.calibration", "{\"mode\":\"start\"}"); });
    server.AddTool("self.desk.calibration_status", "查询已保存的灯带标定状态，不重新标定。", PropertyList(),
        [this](const PropertyList&)->ReturnValue { return Submit("light.calibration", "{\"mode\":\"status\"}"); });
    server.AddTool("self.desk.find_book", "按主书名查找（忽略版本）书架上的书，并使用已保存标定点亮定位灯。不会每次重新标定。返回pending后须用self.desk.result查询，found=false才是本次未可靠找到。",
        PropertyList({Property("title", kPropertyTypeString)}),
        [this](const PropertyList& p)->ReturnValue {
            cJSON* args=cJSON_CreateObject();cJSON_AddStringToObject(args,"title",p["title"].value<std::string>().c_str());
            return Submit("book.find",Dump(args));
        });
    server.AddTool("self.desk.submit", "提交学习桌命令。action包括status,book.find,job.get,timer.start/stop/status/pause/resume,light.scene,exam.set/get/clear,timetable.get/update/config,paper.record.create/get/list/update/delete,wrong_question.create/get/list/update/delete,posture.status/config。params是JSON对象字符串。考试修改先exam.get查询，exam.set用name精确匹配科目，date为YYYY-MM-DD，start/end为HH:MM，location为教室；未提及字段不要传，不得改动其他考试。改名用original_name指定原科目；exam.clear必须传name只删该科目。timetable.get用weekday=1至7查询课程，每页3条，offset翻页；timetable.update用id修改name或location，未确认内容先询问。必须查询result确认完成；simulated是预览，记录管理不会移动纸张。",
        PropertyList({Property("action", kPropertyTypeString), Property("params", kPropertyTypeString, std::string("{}"))}),
        [this](const PropertyList& p)->ReturnValue { return Submit(p["action"].value<std::string>(), p["params"].value<std::string>()); });
    server.AddTool("self.desk.result", "查询request_id的PYNQ执行结果。pending或accepted都不是成功，不要声称动作完成。",
        PropertyList({Property("request_id", kPropertyTypeString)}),
        [this](const PropertyList& p)->ReturnValue {
            auto id = p["request_id"].value<std::string>();
            Tick();
            xSemaphoreTake(lock_, portMAX_DELAY);
            auto it = results_.find(id);
            std::string result = it == results_.end() ? "{\"status\":\"unknown_or_expired\"}" : it->second;
            xSemaphoreGive(lock_); return result;
        });
    server.AddTool("self.desk.last_event", "读取最近的坐姿、番茄钟或故障事件。事件提示音不代表已合成语音。", PropertyList(),
        [this](const PropertyList&)->ReturnValue {
            xSemaphoreTake(lock_, portMAX_DELAY); auto result = last_event_; xSemaphoreGive(lock_); return result;
        });
    // The host hello starts a harmless protocol query after opening the port.
}

std::string AmdBridge::Submit(const std::string& action, const std::string& params) {
    if (!ready_ || !usb_serial_jtag_is_connected()) return "{\"status\":\"usb_unavailable\"}";
    // Motor/physical filing commands are deliberately excluded until mechanics are confirmed.
    static const char* allowed[] = {"paper.status", "paper.home", "paper.feed", "paper.classify", "paper.dispatch", "paper.stop", "paper.release", "protocol.info", "status", "book.find", "book.status", "book.cancel", "book.indicate", "job.get", "light.calibration", "timer.start", "timer.stop", "timer.status", "timer.pause", "timer.resume", "light.scene", "exam.set", "exam.get", "exam.clear", "timetable.get", "timetable.update", "timetable.config", "paper.record.create", "paper.record.get", "paper.record.list", "paper.record.update", "paper.record.delete", "wrong_question.create", "wrong_question.get", "wrong_question.list", "wrong_question.update", "wrong_question.delete", "posture.status", "posture.config", "posture.calibrate"};
    bool valid = false;
    for (auto name : allowed) if (action == name) { valid = true; break; }
    if (!valid)
        return "{\"status\":\"invalid_action\"}";
    cJSON* args = cJSON_Parse(params.c_str());
    if (!cJSON_IsObject(args)) { cJSON_Delete(args); return "{\"status\":\"invalid_params\"}"; }
    xSemaphoreTake(lock_, portMAX_DELAY);
    char id[48]; snprintf(id, sizeof(id), "%08lx-%lu", (unsigned long)esp_random(), (unsigned long)++sequence_);
    cJSON* frame = cJSON_CreateObject();
    cJSON_AddNumberToObject(frame, "v", 1); cJSON_AddStringToObject(frame, "type", "request");
    cJSON_AddStringToObject(frame, "id", id); cJSON_AddStringToObject(frame, "action", action.c_str());
    cJSON_AddItemToObject(frame, "params", args);
    auto wire = Dump(frame) + "\n";
    if (wire.size() > 2049) { xSemaphoreGive(lock_); return "{\"status\":\"frame_too_large\"}"; }
    if (results_.size() >= 32) {
        auto victim = std::find_if(result_order_.begin(), result_order_.end(), [this](const std::string& key) {
            auto state = requests_.find(key);
            return state != requests_.end() && state->second.finished;
        });
        if (victim == result_order_.end()) { xSemaphoreGive(lock_); return "{\"status\":\"busy\"}"; }
        requests_.erase(*victim); results_.erase(*victim); result_order_.erase(victim);
    }
    results_[id] = "{\"status\":\"pending\"}";
    result_order_.push_back(id);
    auto now = esp_timer_get_time();
    RequestState state; state.wire = wire;
    state.deadline = now + 6000000; state.next_retry = now + 2000000;
    state.completion_deadline = now + (action == "paper.classify" ? 180000000 : action == "light.calibration" ? 120000000 : action == "book.find" ? 95000000 : 30000000);
    requests_[id] = state;
    bool sent = WriteWire(wire);
    // Start reply deadlines after paced transmission, not before a long frame.
    auto transmitted_at = esp_timer_get_time();
    requests_[id].deadline = transmitted_at + 6000000;
    requests_[id].next_retry = transmitted_at + 2000000;
    requests_[id].completion_deadline = transmitted_at + (action == "paper.classify" ? 180000000 : action == "light.calibration" ? 120000000 : action == "book.find" ? 95000000 : 30000000);
    if (!sent) { results_[id] = "{\"status\":\"write_failed\",\"execution_unknown\":true}"; requests_[id].finished = true; }
    xSemaphoreGive(lock_);
    cJSON* reply = cJSON_CreateObject(); cJSON_AddStringToObject(reply, "request_id", id);
    cJSON_AddStringToObject(reply, "status", sent ? "pending" : "write_failed"); return Dump(reply);
}

bool AmdBridge::WriteWire(const std::string& wire) {
    if (!usb_serial_jtag_is_connected()) return false;
    const int sent = usb_serial_jtag_write_bytes(wire.data(), wire.size(), pdMS_TO_TICKS(200));
    if (sent != (int)wire.size()) {
        usb_serial_jtag_write_bytes("\n", 1, pdMS_TO_TICKS(20)); return false;
    }
    return usb_serial_jtag_wait_tx_done(pdMS_TO_TICKS(200)) == ESP_OK;
}

void AmdBridge::Tick() {
    xSemaphoreTake(lock_, portMAX_DELAY);
    auto now = esp_timer_get_time();
    for (auto& entry : requests_) {
        auto& state = entry.second;
        if (state.finished) continue;
        if (now >= state.deadline) {
            results_[entry.first] = "{\"status\":\"timeout\",\"execution_unknown\":true}";
            state.finished = true;
        } else if (!state.accepted && now >= state.next_retry && state.attempts < 3) {
            ++state.attempts; state.next_retry = now+2000000;
            if (!WriteWire(state.wire)) {
                results_[entry.first] = "{\"status\":\"write_failed\",\"execution_unknown\":true}";
                state.finished = true;
            }
            state.next_retry = esp_timer_get_time()+2000000;
        }
    }
    xSemaphoreGive(lock_);
}

void AmdBridge::Receive(const std::string& line) {
    cJSON* msg = cJSON_Parse(line.c_str());
    auto version = cJSON_GetObjectItem(msg, "v");
    auto type = cJSON_GetObjectItem(msg, "type");
    if (!cJSON_IsObject(msg) || !cJSON_IsNumber(version) || version->valuedouble != 1 || !cJSON_IsString(type)) { cJSON_Delete(msg); return; }
    if (std::string(type->valuestring) == "hello") {
        auto id = cJSON_GetObjectItem(msg, "id");
        if (!cJSON_IsString(id) || std::string(id->valuestring).size() > 64) { cJSON_Delete(msg); return; }
        const bool probe = cJSON_IsTrue(cJSON_GetObjectItem(msg, "probe"));
        cJSON* reply = cJSON_CreateObject();
        cJSON_AddNumberToObject(reply, "v", 1); cJSON_AddStringToObject(reply, "type", "hello");
        cJSON_AddStringToObject(reply, "id", id->valuestring); cJSON_AddStringToObject(reply, "transport", "usb_serial_jtag");
        xSemaphoreTake(lock_, portMAX_DELAY);
        cJSON_AddStringToObject(reply, "last_result_id", last_result_id_.c_str());
        cJSON_AddStringToObject(reply, "last_result_status", last_result_status_.c_str());
        WriteWire(Dump(reply) + "\n");
        xSemaphoreGive(lock_); cJSON_Delete(msg);
        if (!probe) Submit("protocol.info", "{}");
        return;
    }
    xSemaphoreTake(lock_, portMAX_DELAY);
    bool notify = false;
    bool posture_voice = false;
    if (std::string(type->valuestring) == "result") {
        auto id = cJSON_GetObjectItem(msg, "id");
        auto status = cJSON_GetObjectItem(msg, "status");
        if (cJSON_IsString(id) && cJSON_IsString(status) && results_.count(id->valuestring)) {
            std::string value = status->valuestring;
            auto& state = requests_[id->valuestring];
            if (value == "pending" && !state.finished) {
                state.accepted = true; state.deadline = state.completion_deadline;
                results_[id->valuestring] = line;
            } else if ((value == "success" || value == "failed") && !state.terminal_from_board) {
                state.finished = true; state.terminal_from_board = true;
                results_[id->valuestring] = line;
                last_result_id_ = id->valuestring; last_result_status_ = value;
                ESP_LOGI("AmdBridge", "USB result received id=%s status=%s", id->valuestring, value.c_str());
            }
        }
    } else if (std::string(type->valuestring) == "event") {
        auto name = cJSON_GetObjectItem(msg, "name");
        if (cJSON_IsString(name)) {
            std::string n = name->valuestring;
            posture_voice = n == "posture.bad";
            notify = n == "posture.bad" || n == "timer.finished" || n == "system.error";
            auto event_id = cJSON_GetObjectItem(msg, "event_id");
            if (notify && cJSON_IsString(event_id)) {
                std::string key = event_id->valuestring;
                if (std::find(event_ids_.begin(), event_ids_.end(), key) != event_ids_.end()) notify = false;
                else { event_ids_.push_back(key); if (event_ids_.size()>32) event_ids_.pop_front(); }
            }
            if (notify) last_event_ = line;
        }
    }
    xSemaphoreGive(lock_); cJSON_Delete(msg);
    if (notify) Application::GetInstance().Schedule([posture_voice]() {
        extern const char posture_bad_start[] asm("_binary_posture_bad_ogg_start");
        extern const char posture_bad_end[] asm("_binary_posture_bad_ogg_end");
        if (posture_voice) Application::GetInstance().PlaySound(std::string_view(posture_bad_start, posture_bad_end-posture_bad_start));
        else Application::GetInstance().PlaySound(Lang::Sounds::OGG_POPUP);
    });
}

void AmdBridge::ReceiveTask(void* arg) {
    auto self = static_cast<AmdBridge*>(arg);
    std::string line; bool overflow = false; uint8_t byte;
    for (;;) {
        if (usb_serial_jtag_read_bytes(&byte, 1, pdMS_TO_TICKS(100)) != 1) { self->Tick(); continue; }
        if (byte == '\n') { if (!overflow && !line.empty()) self->Receive(line); line.clear(); overflow = false; self->Tick(); }
        else if (byte != '\r') { if (line.size() < 2048) line += char(byte); else overflow = true; }
    }
}
