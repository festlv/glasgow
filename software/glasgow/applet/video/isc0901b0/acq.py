from nmigen import *
from nmigen.build import Platform
from nmigen.lib.fifo import FIFOInterface
from nmigen.lib.cdc import FFSynchronizer


class ISC0901B0SHRAcq(Elaboratable):
    def __init__(self, pads, in_fifo: FIFOInterface):
        self.pads = pads
        self.in_fifo = in_fifo
        self.input = Signal(2)

        self.pdata_even = Signal(14)
        self.pdata_odd = Signal(14)
        self.bit_ctr = Signal(range(14 + 1), reset=0)
        self.latch = Signal(reset=0)

        self.pdata_even_out = Signal.like(self.pdata_even)
        self.pdata_odd_out = Signal.like(self.pdata_odd)
        self.have_data = Signal()

    def elaborate(self, platform: Platform) -> Module:
        m = Module()

        if self.pads:
            m.d.comb += [
                self.pads.data_even_t.oe.eq(0),
                self.pads.data_odd_t.oe.eq(0),
                self.input[0].eq(self.pads.data_even_t.i),
                self.input[1].eq(self.pads.data_odd_t.i),
            ]
        if platform:
            platform.add_clock_constraint(self.pads.data_even_t.i, 75e6)
            platform.add_clock_constraint(self.pads.data_odd_t.i, 75e6)

        if platform is None:
            m.submodules += self.in_fifo

        with m.If(self.latch):
            m.d.sync += [
                self.bit_ctr.eq(self.bit_ctr + 1),
                self.pdata_even.eq(Cat(self.input[0], self.pdata_even)),
                self.pdata_odd.eq(Cat(self.input[1], self.pdata_even)),

            ]
            with m.If(self.bit_ctr == 13):
                m.d.sync += [
                    self.bit_ctr.eq(1),

                    self.pdata_even_out.eq(self.pdata_even),
                    self.pdata_odd_out.eq(self.pdata_odd),

                    self.pdata_even.eq(self.input[0]),
                    self.pdata_odd.eq(self.input[1]),
                    self.have_data.eq(1)
                ]
        with m.Else():
            m.d.sync += [
                self.pdata_even.eq(0),
                self.pdata_odd.eq(0),
                self.bit_ctr.eq(0)
            ]

        with m.If(self.have_data & self.in_fifo.w_rdy):
            with m.FSM("TX-EVEN-LSB"):
                with m.State("TX-EVEN-LSB"):
                    m.d.comb += [
                        self.in_fifo.w_data.eq(self.pdata_even_out[0:8]),
                        self.in_fifo.w_en.eq(1)
                    ]
                    m.next = "TX-EVEN-MSB"
                with m.State("TX-EVEN-MSB"):
                    m.d.comb += [
                        self.in_fifo.w_data.eq(self.pdata_even_out[8:]),
                        self.in_fifo.w_en.eq(1)
                    ]
                    m.next = "TX-ODD-LSB"
                with m.State("TX-ODD-LSB"):
                    m.d.comb += [
                        self.in_fifo.w_data.eq(self.pdata_odd_out[0:8]),
                        self.in_fifo.w_en.eq(1)
                    ]
                    m.next = "TX-ODD-MSB"
                with m.State("TX-ODD-MSB"):
                    m.d.comb += [
                        self.in_fifo.w_data.eq(self.pdata_odd_out[8:]),
                        self.in_fifo.w_en.eq(1),
                    ]
                    m.d.sync += self.have_data.eq(0)
                    m.next = "TX-EVEN-LSB"

        return m

if __name__ == "__main__":
    from nmigen.sim import *
    from nmigen.lib.fifo import SyncFIFO
    sim_freq = 1e5
    out_fifo = SyncFIFO(width=8, depth=32)
    dut = ISC0901B0SHRAcq(pads=None, in_fifo=out_fifo)
    sim = Simulator(dut)

    def proc():
        yield dut.input.eq(0b0)
        for i in range(16):
            yield

        yield dut.latch.eq(1)
        def w(even, odd):
            for i in range(14):
                yield dut.input[0].eq((even >> i) & 0b1)
                yield dut.input[1].eq((odd >> i) & 0b1)
                yield Tick()

        yield from w(0b01010101010101, 0b01010101010101)
        yield dut.input.eq(0b11)
        for i in range(int(sim_freq * 0.1)):
            yield

    sim.add_clock(1 / sim_freq)

    sim.add_sync_process(proc)
    with sim.write_vcd("acq-dump.vcd", "acq-dump.gtkw"):
        sim.run()