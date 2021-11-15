import logging
from nmigen import *
from nmigen.hdl.cd import ClockDomain
from nmigen.hdl.rec import Record
from nmigen.hdl.xfrm import DomainRenamer
from nmigen.build import Platform
from glasgow.gateware.pll import *
from glasgow.applet import *
from nmigen.lib.fifo import FIFOInterface, AsyncFIFO
from nmigen.lib.cdc import FFSynchronizer, ResetSynchronizer

class SHROutput(Elaboratable):
    def __init__(self, pads):
        self.pads = pads
        self.clk_ctr = Signal(range(14 * 3), reset=0)
        self.output = Signal(2)
        self.latch = Signal()

    def elaborate(self, platform: Platform) -> Module:
        m = Module()
        if self.pads:
            m.d.comb += [
                self.pads.out0_t.oe.eq(1),
                self.pads.out0_t.o.eq(self.output[0]),
                self.pads.out1_t.oe.eq(1),
                self.pads.out1_t.o.eq(self.output[1]),
            ]
        with m.If(self.latch):
            m.d.sync += [
                self.clk_ctr.eq(self.clk_ctr + 1)
            ]
            with m.If(self.clk_ctr == (14 * 3 - 1)):
                m.d.sync += [
                    self.clk_ctr.eq(0)
                ]

            with m.Switch(self.clk_ctr):
                with m.Case("000--0"):
                    m.d.comb += self.output.eq(0b11)
                with m.Default():
                    m.d.comb += self.output.eq(0b00)

        return m


class SHRInput(Elaboratable):
    def __init__(self, pads, in_fifo: FIFOInterface):
        self.pads = pads
        self.in_fifo = in_fifo
        self.input = Signal(2)
        self.input_word = Signal(8, reset=0)
        self.byte_ctr = Signal(1, reset=0)
        self.bit_ctr = Signal(range(7), reset=0)
        self.latch = Signal(reset=0)
        self.input_word_rev = Signal.like(self.input_word)


    def elaborate(self, platform: Platform) -> Module:
        m = Module()

        if self.pads:
            inputs_ff = [Signal(), Signal()]
            m.submodules += [
                FFSynchronizer(self.pads.in0_t.i, inputs_ff[0]),
                FFSynchronizer(self.pads.in1_t.i, inputs_ff[1]),
            ]
            m.d.comb += [
                self.pads.in0_t.oe.eq(0),
                self.input[0].eq(inputs_ff[0]),
                self.pads.in1_t.oe.eq(0),
                self.input[1].eq(inputs_ff[1]),

            ]
        w = self.input_word.width
        for i in range(w):
            m.d.comb += self.input_word_rev[w - i - 1].eq(self.input_word[i])

        with m.If(self.latch):
            m.d.sync += [
                self.bit_ctr.eq(self.bit_ctr + 1),
                self.input_word.eq(Cat(self.input, self.input_word))
            ]
            with m.Switch(self.bit_ctr):
                with m.Case(4):
                    m.d.comb += [
                        self.in_fifo.w_en.eq(1),
                        self.in_fifo.w_data.eq(self.input_word_rev)
                    ]
                    m.d.sync += self.input_word.eq(self.input)
                with m.Case(7):
                    m.d.comb += [
                        self.in_fifo.w_en.eq(1),
                        self.in_fifo.w_data.eq(self.input_word_rev >> 2)
                    ]
                    m.d.sync += [
                        self.bit_ctr.eq(1),
                        self.input_word.eq(self.input)
                    ]
        with m.Else():
            m.d.sync += self.bit_ctr.eq(0)


        return m


class SHRTestTarget(Elaboratable):
    def __init__(self, pads, in_fifo):
        self.pads = pads
        self.in_fifo = in_fifo
        self.clk = ClockSignal("sync_sens")
        self.clk_neg = ClockSignal("sync_sens_neg")

    def elaborate(self, platform: Platform) -> Module:
        m = Module()
        m.domains.sync_sens = cd_sync_sens = ClockDomain("sync_sens")
        sensor_freq = 73.636e6
        m.submodules += PLL(f_in=platform.default_clk_frequency, f_out=sensor_freq, odomain="sync_sens")
        platform.add_clock_constraint(cd_sync_sens.clk, sensor_freq)

        cd_neg = ClockDomain("sync_sens_neg", clk_edge="neg")
        m.domains += cd_neg

        m.submodules.out = DomainRenamer("sync_sens_neg")(SHROutput(self.pads))
        m.submodules.sens_fifo = sens_fifo = AsyncFIFO(width=8, depth=16, r_domain="sync", w_domain="sync_sens")
        m.submodules.inp = DomainRenamer("sync_sens")(SHRInput(self.pads, sens_fifo))
        m.d.comb += [
            ClockSignal("sync_sens_neg").eq(ClockSignal("sync_sens")),
        ]
        latch = Signal()

        m.submodules += ResetSynchronizer(~latch, domain="sync_sens_neg")
        m.d.comb += [
            m.submodules.inp.latch.eq(latch),
            m.submodules.out.latch.eq(latch)
        ]
        if self.pads:
            m.d.comb += [
                self.pads.clk_t.oe.eq(1),
                self.pads.clk_t.o.eq(self.clk),
                self.pads.clk_neg_t.oe.eq(1),
                self.pads.clk_neg_t.o.eq(self.clk_neg),
                self.pads.dbg0_t.oe.eq(1),
                self.pads.dbg0_t.o.eq(m.submodules.inp.bit_ctr == 7),
                self.pads.dbg1_t.oe.eq(1),
                self.pads.dbg1_t.o.eq(m.submodules.out.clk_ctr == 0),

            ]
        m.d.sync_sens += latch.eq(1)
        ctr = Signal(2, reset=0)
        with m.Switch(ctr):
            with m.Case(0):
                with m.If(sens_fifo.r_rdy & self.in_fifo.w_rdy):
                    m.d.sync += [
                        sens_fifo.r_en.eq(1),
                        self.in_fifo.w_data.eq(sens_fifo.r_data),
                        self.in_fifo.w_en.eq(1),
                        ctr.eq(1)
                    ]
            with m.Case(1):
                m.d.sync += [
                    sens_fifo.r_en.eq(0),
                    self.in_fifo.w_en.eq(0),
                    ctr.eq(0)
                ]

        return m


class SHRTestApplet(GlasgowApplet, name="shrtest"):
    logger = logging.getLogger(__name__)
    description = """

    """

    __pins = ("clk", "clk_neg", "out0", "out1", "in0", "in1", "dbg0", "dbg1")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        for pin in cls.__pins:
            access.add_pin_argument(parser, pin, default=True)

    def build(self, target, args, test_pattern=True):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = iface.add_subtarget(SHRTestTarget(
            pads=iface.get_pads(args, pins=self.__pins),
            in_fifo=iface.get_in_fifo(depth=4096, auto_flush=False)
        ))
        return subtarget

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args, pull_high=
        set([i for i in range(len(self.__pins))]))
        data = await iface.read(128)
        txt = ""
        for i in range(len(data)):
            if i % 8 == 0:
                txt += "\n"
            txt = txt + "%02x " % data[i]

        print(txt)
        await iface.reset()



if __name__ == "__main__":
    from nmigen.sim import *
    from nmigen.lib.fifo import SyncFIFO

    sim_freq = 1e5
    out_fifo = SyncFIFO(width=8, depth=32)
    dut = SHRInput(pads=None, in_fifo=out_fifo)
    sim = Simulator(dut)

    def proc():
        yield dut.input.eq(0b11)
        for i in range(16):
            yield

        yield dut.latch.eq(1)
        for i in range(14*2):
            yield

        yield dut.latch.eq(0)
        yield
        yield
        yield

        yield dut.latch.eq(1)
        def w(val):
            print("--------")
            for i in range(7):
                v = (val >> (i * 2)) & 0b11
                print(v)
                yield dut.input.eq(v)
                yield Tick()

#        yield from w(0x3F00)
#        yield from w(0x00FF)
        yield from w(0b11001100110011)
        yield from w(~0b11001100110011)
        yield dut.input.eq(0)
        for i in range(int(sim_freq * 0.1)):
            yield


    sim.add_clock(1 / sim_freq)

    sim.add_sync_process(proc)
    with sim.write_vcd("shrtest.vcd"):
        sim.run()

    dut = SHRTestTarget(None, out_fifo)
    sim = Simulator(dut)
    sim.add_clock(1 / sim_freq)
    def proc():
        for i in range(1024):
            yield

    sim.add_sync_process(proc)
    with sim.write_vcd("shrtesttarget.vcd"):
        sim.run()


