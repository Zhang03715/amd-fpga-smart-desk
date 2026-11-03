// Requests are one-clock events. A host adapter may replace panel_io later.
// Mechanical home is an operator-established reference, never sensor-homed.
module paper_controller #(
    parameter integer PERIOD_CYCLES=130208, WAKE_CYCLES=250000,
    HIGH_CYCLES=625, MIN_PERIOD=12500, SETTLE_CYCLES=62500000,
    FEED_PULSES=22809, EJECT_PULSES=28800,
    CLASS2_PULSES=356, CLASS3_PULSES=489,
    parameter [3:0] DIR_INVERT=4'b0000
)(
    input wire clk, reset, feed_req, classify_req, stop_req, rehome_ack, platform_test_req,
    input wire [1:0] category,
    input wire category_stable,
    output wire [3:0] motor_step, motor_dir, motor_en,
    output wire [3:0] motor_busy,
    output reg [3:0] state=0,
    output reg [1:0] latched_category=0,
    output reg [3:0] error_code=0,
    output reg reference_valid=0,
    output reg [31:0] completed_cycles=0,
    output wire ready_feed, ready_classify,
    output reg [31:0] platform_position=0
);
    localparam BOOT=0, READY=1, FEED=2, WAIT_CLASS=3, ROTATE=4,
        EJECT=5, SETTLE=6, RETURN=7, FAULT=8;
    reg [3:0] starts=0;
    reg [3:0] directions=0;
    reg [31:0] counts[0:3];
    wire [3:0] done, errors;
    wire [31:0] emitted[0:3];
    reg platform_test=0;
    reg seen_busy=0;
    reg [31:0] timer=0, platform_target=0;
    wire halt=stop_req || state==FAULT;
    wire hold_axes=!reset && state!=FAULT && !stop_req;
    assign ready_feed=state==READY;
    assign ready_classify=state==WAIT_CLASS;
    genvar g;
    generate for(g=0;g<4;g=g+1) begin:axes
        pulse_axis #(.WAKE_CYCLES(WAKE_CYCLES),.HIGH_CYCLES(HIGH_CYCLES),
            .MIN_PERIOD(MIN_PERIOD)) axis(
            .clk(clk),.reset(reset),.start(starts[g] && !halt),.stop(halt),
            .idle_hold(hold_axes),.count(counts[g]),.period(PERIOD_CYCLES),
            .direction(directions[g]^DIR_INVERT[g]),
            .step(motor_step[g]),.dir(motor_dir[g]),.en(motor_en[g]),
            .busy(motor_busy[g]),.done(done[g]),.error(errors[g]),.emitted(emitted[g]));
    end endgenerate
    integer i;
    always @(posedge clk) begin
        if(reset) begin
            state<=BOOT;starts<=0;directions<=0;seen_busy<=0;timer<=WAKE_CYCLES-1;
            latched_category<=0;error_code<=0;reference_valid<=0;platform_test<=0;
            platform_target<=0;platform_position<=0;completed_cycles<=0;
            for(i=0;i<4;i=i+1) counts[i]<=0;
        end else begin
            starts<=0;
            if(stop_req || (|errors)) begin
                state<=FAULT;error_code<=stop_req?4'd3:4'd4;reference_valid<=0;
            end else case(state)
            BOOT: begin
                if(timer!=0) timer<=timer-1;
                else begin state<=READY;reference_valid<=1;end
            end
            READY: begin
                if(platform_test_req && !feed_req && !classify_req) begin
                    platform_test<=1;platform_target<=CLASS2_PULSES;counts[3]<=CLASS2_PULSES;
                    directions<=4'b0110;starts<=4'b1000;seen_busy<=0;state<=ROTATE;error_code<=0;
                end else if(feed_req && classify_req) error_code<=1;
                else if(feed_req) begin
                    platform_test<=0;error_code<=0;directions<=4'b0110;
                    counts[0]<=FEED_PULSES;counts[1]<=FEED_PULSES;counts[2]<=FEED_PULSES;
                    starts<=4'b0111;seen_busy<=0;state<=FEED;
                end
                // An early classify event is ignored, never queued.
            end
            FEED: begin
                if((motor_busy&7)==7) seen_busy<=1;
                if(seen_busy && (motor_busy&7)==0) begin
                    if((done&7)!=7 || emitted[0]!=FEED_PULSES || emitted[1]!=FEED_PULSES || emitted[2]!=FEED_PULSES) begin
                        state<=FAULT;error_code<=4;reference_valid<=0;
                    end else state<=WAIT_CLASS;
                end
            end
            WAIT_CLASS: begin
                if(feed_req && classify_req) error_code<=1;
                else if(classify_req) begin
                    if(!category_stable || category==3) error_code<=2;
                    else begin
                        error_code<=0;latched_category<=category;seen_busy<=0;
                        if(category==0) begin
                            platform_target<=0;counts[1]<=EJECT_PULSES;counts[2]<=EJECT_PULSES;
                            directions<=4'b0110;starts<=4'b0110;state<=EJECT;
                        end else begin
                            platform_target<=category==1?CLASS2_PULSES:CLASS3_PULSES;
                            counts[3]<=category==1?CLASS2_PULSES:CLASS3_PULSES;
                            directions<=4'b0110;starts<=4'b1000;state<=ROTATE;
                        end
                    end
                end
            end
            ROTATE: begin
                if(motor_busy[3]) seen_busy<=1;
                if(seen_busy && !motor_busy[3]) begin
                    if(!done[3] || emitted[3]!=platform_target) begin
                        state<=FAULT;error_code<=4;reference_valid<=0;
                    end else begin
                        platform_position<=platform_target;
                        if(platform_test) begin timer<=SETTLE_CYCLES-1;state<=SETTLE;end
                        else begin
                        counts[1]<=EJECT_PULSES;counts[2]<=EJECT_PULSES;
                        directions<=4'b0110;starts<=4'b0110;seen_busy<=0;state<=EJECT;
                        end
                    end
                end
            end
            EJECT: begin
                if((motor_busy&6)==6) seen_busy<=1;
                if(seen_busy && (motor_busy&6)==0) begin
                    if((done&6)!=6 || emitted[1]!=EJECT_PULSES || emitted[2]!=EJECT_PULSES) begin
                        state<=FAULT;error_code<=4;reference_valid<=0;
                    end else begin timer<=SETTLE_CYCLES-1;state<=SETTLE;end
                end
            end
            SETTLE: begin
                if(timer!=0) timer<=timer-1;
                else if(platform_target==0) begin
                    completed_cycles<=completed_cycles+1;state<=READY;
                end else begin
                    directions<=4'b1110;counts[3]<=platform_target;
                    starts<=4'b1000;seen_busy<=0;state<=RETURN;
                end
            end
            RETURN: begin
                if(motor_busy[3]) seen_busy<=1;
                if(seen_busy && !motor_busy[3]) begin
                    if(!done[3] || emitted[3]!=platform_target) begin
                        state<=FAULT;error_code<=4;reference_valid<=0;
                    end else begin
                        platform_position<=0;if(!platform_test)completed_cycles<=completed_cycles+1;platform_test<=0;state<=READY;
                    end
                end
            end
            FAULT: begin
                if(rehome_ack && motor_busy==0 && !stop_req && errors==0) begin
                    // Operator must manually restore mechanical home first.
                    state<=BOOT;timer<=WAKE_CYCLES-1;error_code<=0;platform_test<=0;
                    platform_position<=0;platform_target<=0;seen_busy<=0;
                end
            end
            default: begin state<=FAULT;error_code<=4;reference_valid<=0;end
            endcase
        end
    end
endmodule
