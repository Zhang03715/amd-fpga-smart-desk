#pragma once
#include <string>
#include <map>
#include <deque>
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

class AmdBridge {
    SemaphoreHandle_t lock_ = nullptr;
    uint32_t sequence_ = 0;
    std::map<std::string, std::string> results_;
    std::deque<std::string> result_order_;
    struct RequestState {
        std::string wire;
        int64_t deadline = 0, completion_deadline = 0, next_retry = 0;
        int attempts = 1;
        bool accepted = false, finished = false, terminal_from_board = false;
    };
    std::map<std::string, RequestState> requests_;
    std::deque<std::string> event_ids_;
    std::string last_event_ = "{}";
    bool ready_ = false;
    std::string last_result_id_, last_result_status_;
    static void ReceiveTask(void* arg);
    void Receive(const std::string& line);
    std::string Submit(const std::string& action, const std::string& params);
    bool WriteWire(const std::string& wire);
    void Tick();
public:
    std::string GatewaySubmit(const std::string& action, const std::string& params) { return Submit(action, params); }
    std::string GatewayResult(const std::string& id);
    std::string GatewayEvent();
    static AmdBridge& Instance() { static AmdBridge instance; return instance; }
    void Start();
};
