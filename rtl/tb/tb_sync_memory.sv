module tb_sync_memory;
  logic clk = 1'b0;
  logic rom_enable = 1'b0;
  logic [1:0] rom_address = '0;
  logic [7:0] rom_data;
  logic ram_read_enable = 1'b0;
  logic [1:0] ram_read_address = '0;
  logic [7:0] ram_read_data;
  logic ram_write_enable = 1'b0;
  logic [1:0] ram_write_address = '0;
  logic [7:0] ram_write_data = '0;

  sync_rom #(.WIDTH(8), .DEPTH(4), .ADDRESS_WIDTH(2), .INIT_FILE("sync_rom_test.mem")) rom (
    .clk(clk), .enable(rom_enable), .address(rom_address), .read_data(rom_data)
  );
  sync_ram #(.WIDTH(8), .DEPTH(4), .ADDRESS_WIDTH(2)) ram (
    .clk(clk), .read_enable(ram_read_enable), .read_address(ram_read_address), .read_data(ram_read_data),
    .write_enable(ram_write_enable), .write_address(ram_write_address), .write_data(ram_write_data)
  );

  always #5 clk = ~clk;

  initial begin
    @(negedge clk);
    rom_enable = 1'b1;
    rom_address = 2'd3;
    @(posedge clk);
    #1;
    if (rom_data !== 8'hD4) $fatal(1, "ROM registered read failed");
    @(negedge clk);
    rom_enable = 1'b0;
    @(posedge clk);
    #1;
    if (rom_data !== 8'h00) $fatal(1, "ROM disabled output failed");

    @(negedge clk);
    ram_write_enable = 1'b1;
    ram_write_address = 2'd2;
    ram_write_data = 8'h55;
    @(posedge clk);
    @(negedge clk);
    ram_write_enable = 1'b0;
    ram_read_enable = 1'b1;
    ram_read_address = 2'd2;
    @(posedge clk);
    #1;
    if (ram_read_data !== 8'h55) $fatal(1, "RAM registered read failed");

    @(negedge clk);
    ram_write_enable = 1'b1;
    ram_write_address = 2'd2;
    ram_write_data = 8'hAA;
    @(posedge clk);
    #1;
    if (ram_read_data !== 8'h55) $fatal(1, "RAM must be read-first on collision");
    @(negedge clk);
    ram_write_enable = 1'b0;
    ram_read_enable = 1'b0;
    @(posedge clk);
    #1;
    if (ram_read_data !== 8'h00) $fatal(1, "RAM disabled output failed");
    $display("SYNC MEMORY PASS");
    $finish;
  end
endmodule
