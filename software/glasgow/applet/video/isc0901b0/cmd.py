from nmigen import *
from nmigen.build import Platform
from nmigen.lib.fifo import FIFOInterface


class ISC0901B0SOModule(Elaboratable):
    """
    Module that provides a fifo-backed synchronous output.
    """

    done: Signal
    def __init__(self, fifo: FIFOInterface, msb_first=True):

        self.msb_first = msb_first
        self.fifo = fifo
        self.out = Signal()
        self.bit_ctr = Signal(range(self.fifo.width + 1), reset=0)  # bit counter
        self.out_word = Signal(self.fifo.width, reset=0)
        self.out_word_dbg = Signal(self.fifo.width, reset=0)
        self.out_clk = Signal()
        self.clk = ClockSignal()

        self.have_word = Signal()
        self.done = Signal()

    def elaborate(self, platform: Platform) -> Module:
        m = Module()
        m.submodules.fifo = self.fifo
        if self.msb_first:
            m.d.comb += self.out.eq(self.out_word[self.fifo.width - 1])
        else:
            m.d.comb += self.out.eq(self.out_word[0])

        m.d.comb += self.out_clk.eq(self.clk)
        m.d.comb += self.done.eq(~(self.fifo.r_rdy | self.have_word))
        with m.If(~self.have_word):
            m.d.comb += self.fifo.r_en.eq(1)
            with m.If(self.fifo.r_rdy):
                m.d.sync += [
                    self.out_word.eq(self.fifo.r_data),
                    self.out_word_dbg.eq(self.fifo.r_data),
                    self.have_word.eq(1),

                ]
                m.d.sync += self.bit_ctr.eq(self.bit_ctr + 1)

        with m.Else():
            m.d.comb += self.fifo.r_en.eq(0)
            if self.msb_first:
                m.d.sync += self.out_word.eq(self.out_word.shift_left(1))
            else:
                m.d.sync += self.out_word.eq(self.out_word.shift_right(1))
            m.d.sync += self.bit_ctr.eq(self.bit_ctr + 1)
            with m.If(self.bit_ctr == self.fifo.width):
                m.d.comb += self.fifo.r_en.eq(1)
                with m.If(self.fifo.r_rdy):
                    m.d.sync += [
                        self.out_word.eq(self.fifo.r_data),
                        self.out_word_dbg.eq(self.fifo.r_data),
                        self.bit_ctr.eq(1)
                    ]
                with m.Else():
                    m.d.sync += [
                        self.have_word.eq(0),
                        self.bit_ctr.eq(0)
                    ]

        return m


class ISC0901B0CommandModule(ISC0901B0SOModule):
    """
    Submodule that provides CMD and CLK outputs to sensor.
    CLK is always provided, CMD is shifted out from FIFO.
    """

    ena: Signal

    def __init__(self, pads, fifo):
        super().__init__(fifo)
        self.pads = pads
        self.ena = Signal()

    def elaborate(self, platform) -> Module:
        m = super().elaborate(platform)

        if self.pads:
            m.d.comb += [
                self.pads.cmd_t.oe.eq(1),
                self.pads.cmd_t.o.eq(self.out),
                self.pads.clk_t.oe.eq(1),
                self.pads.clk_t.o.eq(self.out_clk),
                self.pads.ena_t.oe.eq(1),
                self.pads.ena_t.o.eq(self.ena),
            ]
        return m

class ISC0901B0BiasModule(ISC0901B0SOModule):
    """
    Submodule that provides BIAS output to sensor, from the given FIFO.
    """
    def __init__(self, pads, fifo):
        super().__init__(fifo, msb_first=False)
        self.pads = pads

    def elaborate(self, platform) -> Module:
        m = super().elaborate(platform)

        if self.pads:
            m.d.comb += [
                self.pads.bias_t.oe.eq(1),
                self.pads.bias_t.o.eq(self.out),
            ]
        return m


if __name__ == "__main__":

    from nmigen.sim import *
    from nmigen.lib.fifo import SyncFIFO
    fifo = SyncFIFO(width=8, depth=16)
    dut = ISC0901B0CommandModule(pads=None, fifo=fifo)
    sim = Simulator(dut)
    def proc():
        def w(d):
            yield dut.fifo.w_data.eq(d)
            yield dut.fifo.w_en.eq(1)
            yield
            yield dut.fifo.w_en.eq(0)

        data = [0x3f, 0xc0, 0x68, 0xfd, 0xd5, 0x35, 0x56]
        for b in data:
            yield from w(b)

        for i in range(64):
            yield Tick()

        return
        yield Tick()
        yield from w(0x3ffe)
        yield from w(0x3ffe)
        yield from w(0xff)
        yield from w(0x38a2)
        for i in range(256):
            yield Tick()

    sim.add_clock(1/73.5e6)
    sim.add_sync_process(proc)
    with sim.write_vcd("cmd-dump.vcd"):
        sim.run()



    fifo = SyncFIFO(width=7, depth=16)
    dut = ISC0901B0BiasModule(pads=None, fifo=fifo)
    sim = Simulator(dut)

    def proc():
        def w(d):
            yield dut.fifo.w_data.eq(d)
            yield dut.fifo.w_en.eq(1)
            yield
            yield dut.fifo.w_en.eq(0)

        yield from w(0x35)
        yield from w(0x35)
        for i in range(32):
            yield Tick()

        yield from w(0x40)
        for i in range(32):
            yield Tick()

        yield from w(42)
        for i in range(32):
            yield Tick()

        yield from w(0x7f)
        yield from w(0x7f)
        for i in range(32):
            yield Tick()

    sim.add_clock(1/73.5e6)
    sim.add_sync_process(proc)
    with sim.write_vcd("bias-dump.vcd"):
        sim.run()


