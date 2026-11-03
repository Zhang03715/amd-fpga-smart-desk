`timescale 1ns/1ps
// Confirmed adapter pins. 50 MHz FCLK only; no PS GPIO bit-banging.
module adapter_io(
    input wire clk, resetn,
    input wire [31:0] command,
    output wire [31:0] status,
    input wire btn_up_n, btn_down_n, btn_ok_n, btn_back_n,
    output wire lcd_sck, lcd_mosi, lcd_cs_n,
    output reg lcd_dc, lcd_rst_n,
    output wire led1_data, led2_data,
    output wire m1_step, m1_dir, m1_en,
    output wire m2_step, m2_dir, m2_en,
    output wire m3_step, m3_dir, m3_en,
    output wire m4_step, m4_dir, m4_en
);
    reg acknowledge;
    reg spi_start;
    reg [7:0] spi_value;
    reg [23:0] spi_packet;
    reg [1:0] spi_pending;
    wire spi_busy;
    adapter_spi spi(clk,resetn,spi_start,spi_value,spi_busy,lcd_sck,lcd_mosi,lcd_cs_n);
    reg [3:0] buttons;
    (* ASYNC_REG="TRUE" *) reg [3:0] btn_meta, btn_sync;
    reg [19:0] debounce[0:3];
    wire [3:0] raw_buttons = ~{btn_back_n,btn_ok_n,btn_down_n,btn_up_n};
    reg [23:0] pixels0[0:255], pixels1[0:255];
    reg selected_channel;
    reg [7:0] selected_index;
    reg ws_start, ws_channel;
    reg [8:0] ws_count;
    wire [7:0] ws_index;
    wire [23:0] ws_pixel = ws_channel ? pixels1[ws_index] : pixels0[ws_index];
    wire ws_busy, ws_data;
    adapter_ws2812 strip(clk,resetn,ws_start,ws_count,ws_pixel,ws_index,ws_busy,ws_data);
    assign led1_data = ws_channel ? 1'b0 : ws_data;
    assign led2_data = ws_channel ? ws_data : 1'b0;
    reg [3:0] motor_start, motor_direction;
    reg [15:0] motor_count[0:3];
    reg [19:0] motor_period[0:3];
    wire [3:0] motor_step, motor_enable;
    reg [24:0] watchdog;
    reg stop_all;
    wire motor_resetn = resetn && !stop_all && watchdog < 25000000;
    genvar g;
    generate for(g=0;g<4;g=g+1) begin : motors
        adapter_stepper motor(clk,motor_resetn,motor_start[g],motor_count[g],
            motor_period[g],motor_step[g],motor_enable[g]);
    end endgenerate
    assign {m4_step,m3_step,m2_step,m1_step}=motor_step;
    assign {m4_en,m3_en,m2_en,m1_en}=motor_enable;
    assign {m4_dir,m3_dir,m2_dir,m1_dir}=motor_direction;
    wire busy = spi_busy || spi_start || (spi_pending!=0) || ws_busy || ws_start;
    // Bit12 advertises opcode04 (three LCD data bytes, MSB first).
    assign status = {16'h5a32,4'b0001,motor_enable,buttons,2'b0,busy,acknowledge};
    integer i;
    always @(posedge clk) begin
        if (!resetn) begin
            acknowledge<=0;spi_start<=0;spi_value<=0;spi_packet<=0;spi_pending<=0;lcd_dc<=0;lcd_rst_n<=0;
            ws_start<=0;ws_channel<=0;ws_count<=0;selected_channel<=0;selected_index<=0;
            motor_start<=0;motor_direction<=0;watchdog<=25000000;stop_all<=1;
            buttons<=0;btn_meta<=0;btn_sync<=0;
            for(i=0;i<4;i=i+1) begin
                debounce[i]<=0;motor_count[i]<=0;motor_period[i]<=500000;
            end
            for(i=0;i<256;i=i+1) begin pixels0[i]<=0;pixels1[i]<=0;end
        end else begin
            spi_start<=0;ws_start<=0;motor_start<=0;stop_all<=0;
            if(!spi_busy && !spi_start && spi_pending!=0) begin
                lcd_dc<=1;spi_value<=spi_packet[23:16];spi_start<=1;
                spi_packet<={spi_packet[15:0],8'd0};spi_pending<=spi_pending-1;
            end
            btn_meta<=raw_buttons;btn_sync<=btn_meta;
            for(i=0;i<4;i=i+1) begin
                if(btn_sync[i]==buttons[i]) debounce[i]<=0;
                else if(debounce[i]==999999) begin buttons[i]<=btn_sync[i];debounce[i]<=0;end
                else debounce[i]<=debounce[i]+1;
            end
            if(watchdog<25000000) watchdog<=watchdog+1;
            if(command[31]!=acknowledge && !busy) begin
                acknowledge<=command[31];
                case(command[30:24])
                    7'h01: begin lcd_dc<=0;spi_value<=command[7:0];spi_start<=1;end
                    7'h02: begin lcd_dc<=1;spi_value<=command[7:0];spi_start<=1;end
                    7'h03: lcd_rst_n<=command[0];
                    7'h04: begin spi_packet<=command[23:0];spi_pending<=3;end
                    7'h10: begin selected_channel<=command[8];selected_index<=command[7:0];end
                    7'h11: if(selected_channel) pixels1[selected_index]<=command[23:0];
                             else pixels0[selected_index]<=command[23:0];
                    7'h12: if(command[8:0]!=0 && command[8:0]<=256) begin
                        ws_channel<=command[9];ws_count<=command[8:0];ws_start<=1;
                    end
                    7'h30: if(command[18:3]!=0 && !motor_enable[command[1:0]] && watchdog<25000000) begin
                        motor_count[command[1:0]]<=command[18:3];
                        motor_direction[command[1:0]]<=command[2];
                        motor_start[command[1:0]]<=1;
                    end
                    7'h31: if(!motor_enable[command[1:0]] && command[21:2]>=10000) motor_period[command[1:0]]<=command[21:2];
                    7'h3e: watchdog<=0;
                    7'h3f: begin stop_all<=1;watchdog<=25000000;end
                    default: ;
                endcase
            end
        end
    end
endmodule

// SPI mode 0, 5 MHz at a 50 MHz fabric clock; CS brackets each complete byte.
module adapter_spi(input wire clk, resetn, start, input wire [7:0] value,
    output reg busy, output reg sck, mosi, cs_n);
    reg [7:0] shift;
    reg [2:0] bit_index;
    reg [2:0] divider;
    always @(posedge clk) begin
        if(!resetn) begin busy<=0;sck<=0;mosi<=0;cs_n<=1;shift<=0;bit_index<=0;divider<=0;end
        else if(!busy) begin
            if(start) begin busy<=1;cs_n<=0;sck<=0;shift<=value;mosi<=value[7];bit_index<=7;divider<=0;end
        end else if(divider==4) begin
            divider<=0;
            if(!sck) sck<=1;
            else begin
                sck<=0;
                if(bit_index==0) begin busy<=0;cs_n<=1;end
                else begin shift<={shift[6:0],1'b0};mosi<=shift[6];bit_index<=bit_index-1;end
            end
        end else divider<=divider+1;
    end
endmodule

// GRB MSB first: 0=300 ns high, 1=760 ns high, 1260 ns bit, 300 us reset.
module adapter_ws2812(input wire clk, resetn, start, input wire [8:0] count,
    input wire [23:0] pixel, output reg [7:0] index, output wire busy, output reg data);
    reg [2:0] state;
    reg [14:0] ticks;
    reg [4:0] bit_index;
    reg [23:0] word;
    reg [8:0] total;
    assign busy=state!=0;
    always @(posedge clk) begin
        if(!resetn) begin state<=0;ticks<=0;index<=0;data<=0;word<=0;total<=0;bit_index<=23;end
        else case(state)
            0: if(start && count!=0) begin index<=0;total<=count;state<=1;data<=0;end
            1: begin word<=pixel;bit_index<=23;ticks<=0;data<=1;state<=2;end
            2: begin
                if(ticks==(word[bit_index] ? 37 : 14)) data<=0;
                if(ticks==62) begin
                    ticks<=0;
                    if(bit_index==0) begin
                        if({1'b0,index}+1==total) begin state<=3;data<=0;end
                        else begin index<=index+1;state<=1;data<=0;end
                    end else begin bit_index<=bit_index-1;data<=1;end
                end else ticks<=ticks+1;
            end
            3: if(ticks==14999) begin state<=0;ticks<=0;data<=0;end else ticks<=ticks+1;
            default: begin state<=0;data<=0;end
        endcase
    end
endmodule

// Bounded bench move, 1 ms EN wake, 2 us pulse, EN drops after completion.
module adapter_stepper(input wire clk, resetn, start, input wire [15:0] count,
    input wire [19:0] period, output reg step, enable);
    reg [15:0] remaining;
    reg [19:0] phase;
    reg [15:0] wake;
    always @(posedge clk) begin
        if(!resetn) begin step<=0;enable<=0;remaining<=0;phase<=0;wake<=0;end
        else if(!enable) begin
            if(start && count!=0) begin enable<=1;remaining<=count;phase<=0;wake<=0;end
        end else if(wake<50000) wake<=wake+1;
        else begin
            if(phase==0) step<=1;
            if(phase==100) step<=0;
            if(phase>=period-1) begin
                phase<=0;remaining<=remaining-1;
                if(remaining==1) begin enable<=0;step<=0;end
            end else phase<=phase+1;
        end
    end
endmodule
