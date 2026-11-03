// Based on the previously hardware-tested 5us / 2ms pulse generator.
module pulse_axis #(
    parameter integer WAKE_CYCLES=250000, HIGH_CYCLES=625, MIN_PERIOD=12500
)(
    input wire clk, reset, start, stop, idle_hold,
    input wire [31:0] count, period,
    input wire direction,
    output reg step=0, dir=0, en=0, busy=0, done=0, error=0,
    output reg [31:0] emitted=0
);
    reg [31:0] timer=0, target=0, active_period=0;
    reg stopping=0;
    reg [2:0] state=0;
    localparam IDLE=0, WAKE=1, HIGH=2, LOW=3, FINISH=4;
    always @(posedge clk) begin
        if(reset) begin
            step<=0;dir<=0;en<=0;busy<=0;done<=0;error<=0;emitted<=0;
            timer<=0;target<=0;active_period<=0;state<=IDLE;stopping<=0;
        end else begin
            if(stop) stopping<=1;
            if(start && busy) error<=1;
            case(state)
            IDLE: begin
                stopping<=0;
                if(stop) en<=0;
                else if(start) begin
                    done<=0;error<=0;emitted<=0;
                    if(count==0 || period<MIN_PERIOD || period<=HIGH_CYCLES) begin
                        error<=1;en<=0;
                    end else begin
                        target<=count;active_period<=period;dir<=direction;
                        en<=1;busy<=1;timer<=WAKE_CYCLES-1;state<=WAKE;
                    end
                end else en<=idle_hold;
            end
            WAKE: begin
                if(stopping || stop) begin busy<=0;en<=0;state<=IDLE;end
                else if(timer==0) begin
                    step<=1;emitted<=1;timer<=HIGH_CYCLES-1;state<=HIGH;
                end else timer<=timer-1;
            end
            HIGH: begin
                if(timer==0) begin
                    step<=0;timer<=active_period-HIGH_CYCLES-1;
                    if(emitted==target || stopping || stop) state<=FINISH;
                    else state<=LOW;
                end else timer<=timer-1;
            end
            LOW: begin
                if(stopping || stop) begin busy<=0;en<=0;state<=IDLE;end
                else if(timer==0) begin
                    step<=1;emitted<=emitted+1;timer<=HIGH_CYCLES-1;state<=HIGH;
                end else timer<=timer-1;
            end
            FINISH: begin
                if(timer==0) begin
                    busy<=0;done<=!(stopping || stop);
                    en<=idle_hold && !(stopping || stop);state<=IDLE;
                end else timer<=timer-1;
            end
            default: begin state<=IDLE;busy<=0;step<=0;en<=0;error<=1;end
            endcase
        end
    end
endmodule
