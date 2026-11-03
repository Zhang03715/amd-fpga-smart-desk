`timescale 1ns/1ps
module tb_paper_host;
 reg clk=0;always #10 clk=~clk;
 reg resetn=0,take=0,physical_stop=0;reg[6:0]opcode=0;reg[23:0]value=0;
 wire[3:0]step,dir,en;wire debug_active;wire[9:0]debug_data;
 paper_host #(.PERIOD_CYCLES(16),.WAKE_CYCLES(8),.HIGH_CYCLES(4),.MIN_PERIOD(8),.SETTLE_CYCLES(10),.WATCHDOG_CYCLES(200)) dut(.*);
 task cmd(input[6:0]op,input[23:0]v);begin @(negedge clk);opcode=op;value=v;take=1;@(negedge clk);take=0;end endtask
 task wait_state(input[3:0]s);integer count;begin count=0;while(dut.state!=s&&count<500000)begin @(negedge clk);count=count+1;end if(dut.state!=s)$fatal(1,"state timeout %0d actual %0d",s,dut.state);end endtask
 integer counts[0:3];integer j;reg heart=0;
 always @(posedge step[0])counts[0]=counts[0]+1;
 always @(posedge step[1])counts[1]=counts[1]+1;
 always @(posedge step[2])counts[2]=counts[2]+1;
 always @(posedge step[3])counts[3]=counts[3]+1;
 initial begin
  for(j=0;j<4;j=j+1)counts[j]=0;
  repeat(5)@(negedge clk);resetn=1;repeat(20)@(negedge clk);
  if(en!=0||step!=0)$fatal(1,"boot must release axes");
  cmd(7'h41,0);repeat(20)@(negedge clk);if(en!=0)$fatal(1,"feed without reference moved");
  cmd(7'h40,24'h504150);wait_state(1);heart=1;
  cmd(7'h41,0);
  fork
   begin while(heart)begin repeat(40)@(negedge clk);cmd(7'h46,0);end end
   begin
    wait_state(3);
    if(counts[0]!=22809||counts[1]!=22809||counts[2]!=22809||counts[3]!=0)$fatal(1,"feed pulse counts");
    wait(opcode==7'h46);@(negedge clk);repeat(3)@(negedge clk);cmd(7'h42,2);
    wait_state(1);
    if(dut.completed!=1||dut.position!=0)$fatal(1,"completion/reference position");
    if(counts[0]!=22809||counts[1]!=51609||counts[2]!=51609||counts[3]!=978)$fatal(1,"dispatch pulse counts");
    wait(opcode==7'h46);@(negedge clk);repeat(3)@(negedge clk);cmd(7'h47,24'h504c54);
    wait_state(4);wait_state(1);
    if(counts[0]!=22809||counts[1]!=51609||counts[2]!=51609||counts[3]!=1690)$fatal(1,"M4 isolated 356+356 pulse counts");
    if(dut.completed!=1||dut.position!=0)$fatal(1,"M4 test changed paper count or failed return");
    heart=0;
   end
  join
  repeat(220)@(negedge clk);wait_state(8);repeat(20)@(negedge clk);
  if(en!=0||step!=0||dut.reference_valid)$fatal(1,"watchdog failed");
  cmd(7'h41,0);repeat(10)@(negedge clk);if(dut.state!=8)$fatal(1,"fault restarted");
  cmd(7'h40,24'h504150);wait_state(1);cmd(7'h41,0);repeat(30)@(negedge clk);physical_stop=1;
  wait_state(8);repeat(25)@(negedge clk);if(en!=0||step!=0)$fatal(1,"physical stop failed");
  cmd(7'h40,24'h504150);repeat(5)@(negedge clk);if(dut.state!=8)$fatal(1,"home while stop asserted");
  physical_stop=0;repeat(5)@(negedge clk);cmd(7'h40,24'h504150);wait_state(1);cmd(7'h44,0);repeat(40)@(negedge clk);
  if(en!=0||step!=0||dut.enabled)$fatal(1,"release failed");
  $display("PAPER_HOST_SIM_PASS production pulse counts, no boot movement, watchdog, physical stop, manual recovery");$finish;
 end
 initial begin #200000000;$fatal(1,"global timeout");end
endmodule
