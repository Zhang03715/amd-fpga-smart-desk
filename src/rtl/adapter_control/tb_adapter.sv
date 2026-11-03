`timescale 1ns/1ps
module tb_adapter;
    reg clk=0;always #10 clk=~clk;
    reg resetn=0;
    reg [31:0] command=0;
    wire [31:0] status;
    reg up=1,down=1,ok=1,back=1;
    wire sck,mosi,cs,dc,lcd_reset,led1,led2,step,en;
    wire [2:0] other_steps,other_en,other_dir;
    adapter_io dut(.clk(clk),.resetn(resetn),.command(command),.status(status),
        .btn_up_n(up),.btn_down_n(down),.btn_ok_n(ok),.btn_back_n(back),
        .lcd_sck(sck),.lcd_mosi(mosi),.lcd_cs_n(cs),.lcd_dc(dc),.lcd_rst_n(lcd_reset),
        .led1_data(led1),.led2_data(led2),.m1_step(step),.m1_en(en),
        .m2_step(other_steps[0]),.m2_en(other_en[0]),.m2_dir(other_dir[0]),
        .m3_step(other_steps[1]),.m3_en(other_en[1]),.m3_dir(other_dir[1]),
        .m4_step(other_steps[2]),.m4_en(other_en[2]),.m4_dir(other_dir[2]));
    task send(input [6:0] op,input [23:0] value);
        begin
            wait(!status[1]);@(negedge clk);
            command={!command[31],op,value};
            repeat(4) @(negedge clk);
            wait(status[0]==command[31] && !status[1]);
        end
    endtask
    integer spi_bits=0;
    reg [7:0] spi_word=0;
    reg [23:0] spi_history=0;
    always @(posedge sck) if(!cs) begin spi_word={spi_word[6:0],mosi};spi_history={spi_history[22:0],mosi};spi_bits=spi_bits+1;end
    integer led_bits=0;
    time high_start, last_fall;
    always @(posedge led1) begin high_start=$time;led_bits=led_bits+1;end
    always @(negedge led1) if(resetn && led_bits>0) begin
        if($time-high_start!=300 && $time-high_start!=760) $fatal(1,"Bad WS2812 pulse %0t",$time-high_start);
        last_fall=$time;
    end
    integer steps=0, led2_bits=0, m2_count=0, m3_count=0, m4_count=0, i;
    always @(posedge step) steps=steps+1;
    always @(posedge led2) led2_bits=led2_bits+1;
    always @(posedge other_steps[0]) m2_count=m2_count+1;
    always @(posedge other_steps[1]) m3_count=m3_count+1;
    always @(posedge other_steps[2]) m4_count=m4_count+1;
    initial begin
        repeat(5) @(negedge clk);resetn=1;
        repeat(5) @(negedge clk);
        if(en!==0 || step!==0 || led1!==0 || led2!==0) $fatal(1,"Unsafe reset output");
        if(status[31:16]!=16'h5a32) $fatal(1,"Signature mismatch");
        send(7'h02,24'ha5);
        if(spi_bits!=8 || spi_word!=8'ha5 || cs!=1 || sck!=0 || !dc) $fatal(1,"SPI byte failed");
        send(7'h01,24'h2a);
        if(spi_word!=8'h2a || dc) $fatal(1,"SPI DC failed");
        send(7'h03,1); if(!lcd_reset) $fatal(1,"LCD reset failed");
        if(!status[12]) $fatal(1,"LCD triple-byte capability missing");
        send(7'h04,24'h1234ab);
        if(spi_history!=24'h1234ab || spi_bits!=40 || !dc || cs!=1 || sck!=0)
            $fatal(1,"LCD triple-byte ordering/completion failed");
        send(7'h04,24'hff0080);
        if(spi_history!=24'hff0080 || spi_bits!=64) $fatal(1,"Consecutive LCD packets failed");
        send(7'h01,24'h2c);
        if(spi_word!=8'h2c || dc) $fatal(1,"Command after triple-byte packet failed");
        // Reset an unfinished multi-byte transfer and verify a clean restart.
        @(negedge clk);command={!command[31],7'h04,24'haabbcc};
        repeat(20) @(negedge clk);
        resetn=0;command=0;repeat(4) @(negedge clk);
        if(cs!=1 || sck!=0 || status[1]) $fatal(1,"Packet reset did not release SPI");
        resetn=1;repeat(4) @(negedge clk);
        send(7'h04,24'h070809);
        if(spi_history!=24'h070809 || !dc) $fatal(1,"Packet restart after reset failed");
        send(7'h10,0);send(7'h11,24'h123456);send(7'h12,1);
        if(led_bits!=24 || $time-last_fall<300000 || led2!==0) $fatal(1,"LED frame/reset failed");
        for(i=0;i<256;i=i+1) begin
            send(7'h10,256+i);send(7'h11,24'hff00ff);
        end
        send(7'h12,768); // second channel, maximum 256 pixels
        if(led2_bits!=6144 || led_bits!=24 || led1!==0 || led2!==0) $fatal(1,"Second channel/max frame failed");
        up=0;repeat(100) @(negedge clk);up=1;
        repeat(100) @(negedge clk);
        if(status[4]) $fatal(1,"Button bounce passed filter");
        up=0;repeat(1000010) @(negedge clk);
        if(!status[4]) $fatal(1,"Button press missing");
        send(7'h31,40000); // motor 0, period 10000 cycles
        send(7'h3e,0);send(7'h30,24'd24); // three steps
        wait(en);wait(!en);
        if(steps!=3 || step!==0) $fatal(1,"Finite move failed");
        send(7'h3e,0);send(7'h30,24'd800);wait(en);
        send(7'h3f,0);repeat(4) @(negedge clk);
        if(en!==0 || step!==0) $fatal(1,"Stop failed");
        send(7'h3e,0);send(7'h30,24'd800);wait(en);
        @(negedge clk);dut.watchdog=24999995;
        repeat(10) @(negedge clk);
        if(en!==0 || step!==0) $fatal(1,"Watchdog failed");
        for(i=1;i<4;i=i+1) send(7'h31,40000+i);
        send(7'h3e,0);
        for(i=1;i<4;i=i+1) send(7'h30,24'd20+i); // two steps, DIR high
        wait(other_en==3'b111);wait(other_en==0);
        if(m2_count!=2 || m3_count!=2 || m4_count!=2 || other_steps!=0 || other_dir!=3'b111)
            $fatal(1,"Independent motor channels failed");
        $display("PASS: SPI byte/DC/reset, WS2812 pulse/reset/two channels/256 pixels, button debounce, four motor count/stop/watchdog");
        $finish;
    end
    initial begin #100000000; $fatal(1,"Simulation timeout");end
endmodule
