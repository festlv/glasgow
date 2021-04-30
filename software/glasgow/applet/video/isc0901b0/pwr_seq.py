from nmigen import *
from nmigen.build import Platform


class ISC0901B0PowerSequencing(Elaboratable):

    ready: Signal

    def __init__(self, pads, clk_freq):
        self.pads = pads
        self.clk_freq = clk_freq
        self.state_delays_us = (500, 15000, 4000)  # 3v3_en -> 2v5_en -> boost_en
        self.cyc_ctr = Signal(range(int(clk_freq / 1e6 * (max(self.state_delays_us) + 1))), reset=0)  # counter for the state transitions,
        # should be wide enough for the maximum possible delay

        # output signals from FSM
        self.en_3v3 = Signal(reset=0)
        self.en_2v5 = Signal(reset=0)
        self.en_boost = Signal(reset=0)
        self.bias_9v0 = Signal(reset=0)

        # output to higher modules, indicates that power sequencing is done
        self.ready = Signal()


    def elaborate(self, platform: Platform) -> Module:
        m = Module()
        m.d.sync += self.cyc_ctr.eq(self.cyc_ctr + 1)
        if platform:
            led = platform.request("led", 0)
            m.d.comb += led.eq(self.ready)
        if self.pads:
            m.d.comb += [
                self.pads.en_3v3_t.oe.eq(1),
                self.pads.en_3v3_t.o.eq(self.en_3v3),
                self.pads.en_2v5_t.oe.eq(1),
                self.pads.en_2v5_t.o.eq(self.en_2v5),
#                self.pads.en_boost_t.oe.eq(1),
#                self.pads.en_boost_t.o.eq(self.en_boost),
#                self.pads.bias_9v0_t.oe.eq(1),
#                self.pads.bias_9v0_t.o.eq(self.bias_9v0),
            ]

        with m.FSM("INIT"):
            with m.State("INIT"):
                m.d.sync += [
                    self.en_2v5.eq(0),
                    self.en_3v3.eq(0),
                    self.en_boost.eq(0),
                    self.bias_9v0.eq(0),
                ]
                with m.If(self.cyc_ctr > int(self.clk_freq / 1e6 * self.state_delays_us[0])):
                    m.d.sync += [
                        self.en_3v3.eq(1),
                        self.cyc_ctr.eq(0)
                    ]
                    m.next = "3V3_EN"
            with m.State("3V3_EN"):
                with m.If(self.cyc_ctr > int(self.clk_freq / 1e6 * self.state_delays_us[1])):
                    m.d.sync += [
                        self.en_2v5.eq(1),
                        self.cyc_ctr.eq(0)
                    ]
                    m.next = "2V5_EN"
            with m.State("2V5_EN"):
                with m.If(self.cyc_ctr > int(self.clk_freq / 1e6 * self.state_delays_us[2])):
                    m.d.sync += [
                        self.en_boost.eq(1),
                        self.cyc_ctr.eq(0)
                    ]
                    m.next = "BOOST_EN"
            with m.State("BOOST_EN"):
                m.d.comb += [self.ready.eq(1)]

        return m


if __name__ == "__main__":
    from nmigen.sim import *
    dut = ISC0901B0PowerSequencing(pads=None, clk_freq=1e5)
    sim = Simulator(dut)

    def proc():
        for i in range(int(1e4)):
            yield Tick()

    sim.add_clock(1e-5)
    sim.add_sync_process(proc)
    with sim.write_vcd("pwr-seq-dump.vcd", "pwr-seq-dump.gtkw"):
        sim.run()