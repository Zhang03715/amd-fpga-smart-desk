#include "wifi_board.h"
#include "codecs/no_audio_codec.h"
#include "display/oled_display.h"
#include <driver/i2c_master.h>
#include <esp_lcd_panel_vendor.h>
#include <esp_log.h>
#include "application.h"
#include "button.h"
#include "config.h"
#include "amd_bridge.h"
#include "amd_gateway.h"

class AmdBoard : public WifiBoard {
    NoDisplay fallback_display_;
    Display* display_ = &fallback_display_;
    i2c_master_bus_handle_t display_bus_ = nullptr;
    esp_lcd_panel_io_handle_t panel_io_ = nullptr;
    esp_lcd_panel_handle_t panel_ = nullptr;

    void InitializeDisplay() {
        i2c_master_bus_config_t bus = {};
        bus.i2c_port = I2C_NUM_0;
        bus.sda_io_num = DISPLAY_SDA_PIN;
        bus.scl_io_num = DISPLAY_SCL_PIN;
        bus.clk_source = I2C_CLK_SRC_DEFAULT;
        bus.glitch_ignore_cnt = 7;
        bus.flags.enable_internal_pullup = true;
        ESP_ERROR_CHECK(i2c_new_master_bus(&bus, &display_bus_));
        int address = 0;
        for (int attempt = 0; attempt < 5 && !address; ++attempt) {
          vTaskDelay(pdMS_TO_TICKS(200));
          for (int candidate : {0x3c, 0x3d}) {
            if (i2c_master_probe(display_bus_, candidate, 100) == ESP_OK) {
                address = candidate;
                break;
            }
        }
        }
        if (!address) {
            ESP_LOGE("AmdOLED", "No OLED ACK: SDA=42 SCL=41; continuing without display");
            return;
        }
        esp_lcd_panel_io_i2c_config_t io = {};
        io.dev_addr = address;
        io.control_phase_bytes = 1;
        io.dc_bit_offset = 6;
        io.lcd_cmd_bits = 8;
        io.lcd_param_bits = 8;
        io.scl_speed_hz = 100000;
        ESP_ERROR_CHECK(esp_lcd_new_panel_io_i2c_v2(display_bus_, &io, &panel_io_));
        esp_lcd_panel_ssd1306_config_t vendor = {};
        vendor.height = DISPLAY_HEIGHT;
        esp_lcd_panel_dev_config_t panel_config = {};
        panel_config.reset_gpio_num = -1;
        panel_config.bits_per_pixel = 1;
        panel_config.vendor_config = &vendor;
        ESP_ERROR_CHECK(esp_lcd_new_panel_ssd1306(panel_io_, &panel_config, &panel_));
        ESP_ERROR_CHECK(esp_lcd_panel_reset(panel_));
        ESP_ERROR_CHECK(esp_lcd_panel_init(panel_));
        ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(panel_, true));
        display_ = new OledDisplay(panel_io_, panel_, DISPLAY_WIDTH, DISPLAY_HEIGHT,
                                   DISPLAY_MIRROR_X, DISPLAY_MIRROR_Y);
        ESP_LOGI("AmdOLED", "SSD1306 ready address=0x%02x SDA=42 SCL=41", address);
    }
    Button boot_{GPIO_NUM_0};
    // External 10k pull-ups: switches connect to GND when pressed.
    Button talk_{TOUCH_BUTTON_GPIO, false};
    Button dialog_{DIALOG_BUTTON_GPIO, false};
    Button volume_up_{VOLUME_UP_BUTTON_GPIO, false};
    Button volume_down_{VOLUME_DOWN_BUTTON_GPIO, false};

    void ChangeVolume(int delta) {
        Application::GetInstance().Schedule([this, delta]() {
            auto* codec = GetAudioCodec();
            int volume = codec->output_volume() + delta;
            if (volume < 0) volume = 0;
            if (volume > 100) volume = 100;
            codec->SetOutputVolume(volume);
        });
    }
public:
    AmdBoard() {
        InitializeDisplay();
        AmdBridge::Instance().Start();
        talk_.OnPressDown([]() {
            Application::GetInstance().StartListening();
        });
        talk_.OnPressUp([]() {
            Application::GetInstance().StopListening();
        });
        dialog_.OnClick([]() {
            Application::GetInstance().ToggleChatState();
        });
        volume_up_.OnClick([this]() { ChangeVolume(10); });
        volume_down_.OnClick([this]() { ChangeVolume(-10); });
        boot_.OnClick([this]() {
            auto& app = Application::GetInstance();
            if (app.GetDeviceState() == kDeviceStateStarting) EnterWifiConfigMode();
            else app.ToggleChatState();
        });
    }
    void StartNetwork() override { WifiBoard::StartNetwork(); StartAmdGateway(); }
    Display* GetDisplay() override { return display_; }
    AudioCodec* GetAudioCodec() override {
        static NoAudioCodecSimplex codec(16000, 24000,
            GPIO_NUM_15, GPIO_NUM_16, GPIO_NUM_7, I2S_STD_SLOT_LEFT,
            GPIO_NUM_5, GPIO_NUM_4, GPIO_NUM_6, I2S_STD_SLOT_LEFT);
        return &codec;
    }
};
DECLARE_BOARD(AmdBoard);
