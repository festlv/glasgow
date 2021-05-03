import logging
from nmigen import *
from nmigen.hdl.cd import ClockDomain
from nmigen.hdl.xfrm import DomainRenamer
from nmigen.build import Platform
from glasgow.gateware.pll import *
from glasgow.applet.video.isc0901b0.main import ISC0901B0Main
from nmigen.lib.fifo import AsyncFIFO
from nmigen.lib.cdc import ResetSynchronizer



class ISC0901B0Subtarget(Elaboratable):
    def __init__(self, pads, in_fifo):
        self.pads = pads
        self.in_fifo = in_fifo
        self.startup_ctr = Signal(range(8))

    def elaborate(self, platform: Platform) -> Module:
        m = Module()

        m.domains.sync_sens = cd_sync_sens = ClockDomain("sync_sens")
        sensor_freq = 73.636e6
        if platform:
            m.submodules += PLL(f_in=platform.default_clk_frequency, f_out=sensor_freq, odomain="sync_sens")
            platform.add_clock_constraint(cd_sync_sens.clk, sensor_freq)

        m.submodules.acq_fifo = acq_fifo = AsyncFIFO(width=8, depth=128, w_domain="sync_sens", r_domain="sync")
        m.submodules.main = main = DomainRenamer("sync_sens")(ISC0901B0Main(self.pads, acq_fifo, sensor_freq))

        # keep write domain in reset for some time to clear async FIFO
        with m.If(self.startup_ctr < 7):
            m.d.sync += self.startup_ctr.eq(self.startup_ctr + 1)

        m.submodules += ResetSynchronizer(~(self.startup_ctr == 7), domain="sync_sens")

        fifo_read = Signal()
        m.d.comb += fifo_read.eq(acq_fifo.r_rdy & self.in_fifo.w_rdy)
        m.d.comb += [
            acq_fifo.r_en.eq(fifo_read),
            self.in_fifo.w_en.eq(fifo_read),
            self.in_fifo.w_data.eq(acq_fifo.r_data)
        ]

        if self.pads:
            for i in range(8):
                m.d.comb += getattr(self.pads, "d%d_t" % i).oe.eq(1)
#                m.d.comb += getattr(self.pads, "d%d_t" % i).o.eq(main.acq.input_word_rev[i])

            m.d.comb += self.pads.d0_t.o.eq(acq_fifo.w_en)

        if platform is None:
            m.submodules += self.in_fifo

        #ctr = Signal(2, reset=0)
        #with m.Switch(ctr):
        #    with m.Case(0):
        #        with m.If(acq_fifo.r_rdy & self.in_fifo.w_rdy):
        #            m.d.sync += [
        #                acq_fifo.r_en.eq(1),
        #                self.in_fifo.w_data.eq(acq_fifo.r_data),
        #                self.in_fifo.w_en.eq(1),
        #                ctr.eq(1)
        #            ]
        #    with m.Case(1):
        #        m.d.sync += [
        #            acq_fifo.r_en.eq(0),
        #            self.in_fifo.w_en.eq(0),
        #            ctr.eq(0)
        #        ]

        return m


if __name__ == "__main__":
    from nmigen.sim import *
    from nmigen.lib.fifo import SyncFIFO

    sim_freq = 48e6
    sens_freq = 75e6
    out_fifo = SyncFIFO(width=16, depth=32)
    dut = ISC0901B0Subtarget(pads=None, in_fifo=out_fifo)
    sim = Simulator(dut)

    sim_time = 0.05
    log = logging.getLogger("sim")

    def sync_sens_process():
        for i in range(int(sens_freq * sim_time)):
            if i % int(sens_freq * 0.001) == 0:
                print("sync_sens: %.3fms/%.3fms" % (1/sens_freq * i * 1000, sim_time * 1000))
            yield Tick("sync_sens")


    sim.add_sync_process(sync_sens_process, domain="sync_sens")
    sim.add_clock(1 / sens_freq, domain="sync_sens")


    def sync_process():
        yield out_fifo.r_en.eq(1)
        for i in range(int(sim_freq * sim_time)):
            if i % int(sim_freq * 0.001) == 0:
                print("sync: %.3fms/%.3fms" % (1 / sim_freq * i * 1000, sim_time * 1000))
            yield Tick("sync")


    sim.add_sync_process(sync_process, domain="sync")
    sim.add_clock(1 / sim_freq, domain="sync")

    with sim.write_vcd("applet.vcd"):
        sim.run()
