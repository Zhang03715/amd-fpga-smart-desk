// Host bridge for teammate motion core, rescaled from 125 MHz to FCLK50.
// Boot disables all axes. Home is an explicit operator acknowledgement, not sensor homing.
module paper_host #(
 parameter integer PERIOD_CYCLES=43403,WAKE_CYCLES=100000,HIGH_CYCLES=250,
 MIN_PERIOD=5000,SETTLE_CYCLES=25000000,WATCHDOG_CYCLES=100000000
)(input wire clk,resetn,take,input wire [6:0] opcode,input wire [23:0] value,
 input wire physical_stop,output wire [3:0] step,dir,en,
 output wire debug_active,output reg [9:0] debug_data);
 reg enabled=0,release_pending=0,feed=0,dispatch=0,stop=0,rehome=0;
 reg [1:0] category=0;reg platform_test=0;reg [2:0] page=0;
 reg [26:0] watchdog=0;reg expired=0;
 (* ASYNC_REG="TRUE" *) reg stop_meta=0,stop_sync=0;
 wire [3:0] state,error_code,busy,latched;
 wire [1:0] latched_category;wire reference_valid,ready_feed,ready_classify;
 wire [31:0] completed,position;
 wire halt=stop || stop_sync || expired;
 assign debug_active=page!=0;
 paper_controller #(.PERIOD_CYCLES(PERIOD_CYCLES),.WAKE_CYCLES(WAKE_CYCLES),
 .HIGH_CYCLES(HIGH_CYCLES),.MIN_PERIOD(MIN_PERIOD),.SETTLE_CYCLES(SETTLE_CYCLES)) core(
 .clk(clk),.reset(!resetn || !enabled),.feed_req(feed),.classify_req(dispatch),
 .platform_test_req(platform_test),.stop_req(halt),.rehome_ack(rehome),.category(category),.category_stable(1'b1),
 .motor_step(step),.motor_dir(dir),.motor_en(en),.motor_busy(busy),.state(state),
 .latched_category(latched_category),.error_code(error_code),.reference_valid(reference_valid),
 .completed_cycles(completed),.ready_feed(ready_feed),.ready_classify(ready_classify),.platform_position(position));
 always @* begin
  case(page)
   1:debug_data={stop_sync,expired,enabled,reference_valid,error_code[1:0],state};
   2:debug_data=completed[9:0];3:debug_data=completed[19:10];4:debug_data=completed[29:20];
   5:debug_data={6'b0,error_code[3:2],completed[31:30]};
   6:debug_data=position[9:0];
   7:debug_data={latched_category,busy,step};
   default:debug_data=0;
  endcase
 end
 always @(posedge clk) begin
  if(!resetn) begin
   enabled<=0;release_pending<=0;feed<=0;dispatch<=0;stop<=0;rehome<=0;platform_test<=0;category<=0;page<=0;
   watchdog<=0;expired<=0;stop_meta<=0;stop_sync<=0;
  end else begin
   stop_meta<=physical_stop;stop_sync<=stop_meta;
   feed<=0;dispatch<=0;stop<=0;rehome<=0;platform_test<=0;
   if(enabled && !expired) begin
    if(watchdog==WATCHDOG_CYCLES-1)expired<=1;else watchdog<=watchdog+1;
   end
   if(release_pending && busy==0 && state==8) begin enabled<=0;release_pending<=0;end
   if(take) case(opcode)
    7'h40:if(value==24'h504150 && busy==0 && !stop_sync && (!enabled || state==8)) begin
      enabled<=1;release_pending<=0;expired<=0;watchdog<=0;rehome<=1;
    end
    7'h41:if(enabled && reference_valid && ready_feed && !halt)feed<=1;
    7'h42:if(enabled && reference_valid && ready_classify && !halt)begin category<=value[1:0];dispatch<=1;end
    7'h43,7'h3f:stop<=1;
    7'h44:if(enabled)begin stop<=1;release_pending<=1;end
    7'h45:page<=value[2:0];
    7'h46:if(enabled)watchdog<=0;
    7'h47:if(value==24'h504c54 && enabled && reference_valid && ready_feed && !halt)platform_test<=1;
    default:;
   endcase
  end
 end
endmodule
