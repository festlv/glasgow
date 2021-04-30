from nmigen import *
from nmigen.build import Platform
from nmigen.lib.fifo import FIFOInterface
from nmigen.lib.cdc import FFSynchronizer


class ISC0901B0AcqModule(Elaboratable):
    """
    Module that provides a fifo-backed synchronous input.
    Input is two bits per clock (on two data lanes), so acq_width must be a multiple of 2
    """

    latch: Signal  # latch signal- acquire consecutive

    def __init__(self, pads, fifo: FIFOInterface, acq_width=14):
        self.pads = pads
        self.fifo = fifo
        self.input = Signal(2)
        self.acq_width = acq_width
        assert self.acq_width % 2 == 0, "Acquisition width must be a multiple of 2"
        self.nibble_ctr = Signal(range((self.acq_width // 2) + 1), reset=0)  # bit counter

        self.input_word = Signal(self.acq_width, reset=0)
        self.latch = Signal()


    def elaborate(self, platform: Platform) -> Module:
        m = Module()
        m.submodules.fifo = self.fifo

        if self.pads:
            input_ffs = [Signal(), Signal()]
            m.submodules += [
                FFSynchronizer(self.pads.data_even_t.i, input_ffs[0]),
                FFSynchronizer(self.pads.data_odd_t.i, input_ffs[1]),
            ]

            m.d.comb += [
                self.pads.data_even_t.oe.eq(0),
                self.pads.data_odd_t.oe.eq(0),
                self.input.eq(Cat(input_ffs[0], input_ffs[1]))
            ]

        with m.If(self.latch):
            m.d.sync += [
                #self.input_word.eq(Cat(self.input, self.input_word)),
                self.input_word.bit_select((self.acq_width//2 - (1 + self.nibble_ctr)) * 2, 2).eq(self.input),
                self.nibble_ctr.eq(self.nibble_ctr + 1)
            ]
            with m.If(self.nibble_ctr == ((self.acq_width // 2))):
                m.d.comb += [
                    self.fifo.w_en.eq(1),
                    self.fifo.w_data.eq(self.input_word),
                ]
                m.d.sync += [
                    self.nibble_ctr.eq(1),
                    self.input_word.bit_select((self.acq_width // 2 - 1) * 2, 2).eq(self.input),
                    #self.input_word.eq(self.input)
                ]
            with m.Else():
                m.d.comb += self.fifo.w_en.eq(0)
        with m.Else():
            m.d.sync += [
                self.nibble_ctr.eq(0),
                self.input_word.eq(0)
            ]
            m.d.comb += self.fifo.w_en.eq(0)

        return m

class ISC0901B0SHRAcq(Elaboratable):
    def __init__(self, pads, in_fifo: FIFOInterface):
        self.pads = pads
        self.in_fifo = in_fifo
        self.input = Signal(2)
        self.input_word = Signal(8, reset=0)
        self.byte_ctr = Signal(1, reset=0)
        self.bit_ctr = Signal(range(8), reset=0)
        self.latch = Signal(reset=0)
        self.input_word_rev = Signal.like(self.input_word)


    def elaborate(self, platform: Platform) -> Module:
        m = Module()

        if self.pads:
#            inputs_ff = [Signal(), Signal()]
#            m.submodules += [
#                FFSynchronizer(self.pads.data_even_t.i, inputs_ff[0], stages=4),
#                FFSynchronizer(self.pads.data_odd_t.i, inputs_ff[1], stages=4),
#            ]
            m.d.comb += [
                self.pads.data_even_t.oe.eq(0),
                self.pads.data_odd_t.oe.eq(0),

#                self.input[0].eq(inputs_ff[0]),
#                self.input[1].eq(inputs_ff[1]),
                self.input[0].eq(self.pads.data_even_t.i),
                self.input[1].eq(self.pads.data_odd_t.i),

            ]
        if platform:
            platform.add_clock_constraint(self.pads.data_even_t.i, 48e6)
            platform.add_clock_constraint(self.pads.data_odd_t.i, 48e6)

        w = self.input_word.width
        for i in range(w):
            m.d.comb += self.input_word_rev[w - i - 1].eq(self.input_word[i])

        with m.If(self.latch | (self.bit_ctr > 3)):
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
                    m.d.sync += self.input_word.eq(Cat(self.input, Const(0, 6)))
                with m.Case(7):
                    m.d.comb += [
                        self.in_fifo.w_en.eq(1),
                        self.in_fifo.w_data.eq(self.input_word_rev[2:])
                    ]
                    m.d.sync += [
                        self.bit_ctr.eq(1),
                        self.input_word.eq(self.input)
                    ]
        with m.Else():
            m.d.sync += [
                self.bit_ctr.eq(0),
                self.input_word.eq(0)
            ]



        return m

if __name__ == "__main__":
    from nmigen.sim import *
    from nmigen.lib.fifo import SyncFIFO
    sim_freq = 1e5
    out_fifo = SyncFIFO(width=16, depth=32)
    dut = ISC0901B0AcqModule(pads=None, fifo=out_fifo)
    sim = Simulator(dut)

    def proc():
        yield dut.input.eq(0b11)
        for i in range(16):
            yield

        yield dut.latch.eq(1)
        def w(val):
            print("--------")
            for i in range(7):
                v = (val >> (i * 2)) & 0b11
                print(v)
                yield dut.input.eq(v)
                yield Tick()
        yield from w(0x3F00)
        yield from w(0x00FF)
        yield from w(0b01010101010101)
        yield dut.input.eq(0)
        for i in range(int(sim_freq * 0.1)):
            yield

    sim.add_clock(1 / sim_freq)

    sim.add_sync_process(proc)
    with sim.write_vcd("acq-dump.vcd", "acq-dump.gtkw"):
        sim.run()