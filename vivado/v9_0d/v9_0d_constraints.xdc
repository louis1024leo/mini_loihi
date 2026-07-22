create_clock -name v9_0d_clk -period 10.000 [get_ports clk]
set_clock_uncertainty 0.000 [get_clocks v9_0d_clk]
