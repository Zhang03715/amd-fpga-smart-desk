# Integrated paper sorter

The host clock is 50 MHz. `paper_host.sv` sets the step period to 43,403 clocks
(approximately 1,152 pulses/second).

The feed stage uses 22,809 pulses (approximately 19.8 seconds). The eject stage drives M2/M3 for 28,800
pulses, approximately 25 seconds, as of 2026-11-04. Slot 2 uses 356 M4 pulses (about 40 degrees); slot 3 uses 489 pulses (about 55 degrees). The return uses the same pulse count. Direction,
settling, watchdog and stop behavior are unchanged.

Run `sim.tcl` before `build.tcl`. The simulation checks emitted pulse counts,
M4 return, boot inactivity, watchdog, physical stop and manual recovery.
The build checks timing coverage, setup and hold slack before writing the bitstream.

Updating the overlay resets its platform reference. The operator must place
the platform at slot 1 and explicitly confirm the reference before sorting.
There is no automatic homing or physical paper-delivery feedback.
