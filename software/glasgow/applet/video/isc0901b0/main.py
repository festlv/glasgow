from nmigen import *
from nmigen.build import Platform
from nmigen.lib.fifo import AsyncFIFO, SyncFIFO, FIFOInterface
from glasgow.applet.video.isc0901b0.cmd import ISC0901B0CommandModule, ISC0901B0BiasModule
from glasgow.applet.video.isc0901b0.pwr_seq import ISC0901B0PowerSequencing
from glasgow.applet.video.isc0901b0.acq import ISC0901B0AcqModule, ISC0901B0SHRAcq


class ISC0901B0Main(Elaboratable):
    """
    Main module operates at sensor clock frequency
    """
    data_out_fifo: FIFOInterface

    def __init__(self, pads, data_out_fifo: FIFOInterface, sensor_clk_freq=73.5e6):
        self.pads = pads
        self.sensor_clk_freq = sensor_clk_freq
        self.data_out_fifo = data_out_fifo
        cmd_words_val = [0xff, 0x38a2, 0x36a7, 0x26aa, 0x30b7, 0x3f63, 0x04ff, 0x2212, 0x1cc4, 0x0b8d, 0x3018, 0x1020]
        self.cmd_words = Array([Const(v, unsigned(14)) for v in cmd_words_val])
        self.init_ctr = Signal(range(32), reset=0)
        self.cmd_word_ctr = Signal(range(len(self.cmd_words)))

        self.dbg_fifo_ctr = Signal(range(1024), reset=0)
        self.dbg_fifo_data = Signal(range(1024), reset=0)

        self.line_start_ctr = Signal(range(1024 * 7))

        self.w_ctr = Signal(3, reset=0)

        self.latch_bias  = Signal()
        self.bias_ctr = Signal(range(339))
        self.line_clk_ctr = Signal(range(339 * 7 + 64), reset=0)

        self.frame_valid = Signal()
        self.row_ctr = Signal(range(256+32), reset=0)

        self.bias_value = 0x25
        self.bias_to_latch_cyc = 4


    def elaborate(self, platform: Platform) -> Module:
        m = Module()
        m.submodules.pwr_seq = self.pwr_seq = ISC0901B0PowerSequencing(pads=self.pads,
                                                                       clk_freq=self.sensor_clk_freq)
        cmd_fifo = SyncFIFO(width=14, depth=len(self.cmd_words))
        m.submodules.cmd = self.cmd = ISC0901B0CommandModule(self.pads, cmd_fifo)

        bias_fifo = SyncFIFO(width=7, depth=16)
        m.submodules.bias = self.bias = ISC0901B0BiasModule(self.pads, bias_fifo)

#        acq_fifo = SyncFIFO(width=16, depth=128)
#        m.submodules.acq = self.acq = ISC0901B0AcqModule(self.pads, acq_fifo)
        m.submodules.acq = self.acq = ISC0901B0SHRAcq(self.pads, self.data_out_fifo)

        m.d.comb += [
            self.cmd.ena.eq(self.pwr_seq.en_2v5),
        ]
        if self.pads:
            for i in range(8):
                m.d.comb += getattr(self.pads, "d%d_t" % i).oe.eq(1)
                m.d.comb += getattr(self.pads, "d%d_t" % i).o.eq(self.acq.input_word_rev[i])

            a0 = platform.request("aux", 0, dir="o")
            a1 = platform.request("aux", 1, dir="o")
            m.d.comb += [
                a0.eq(self.data_out_fifo.w_en),
                a1.eq(self.acq.latch)
            ]

        if platform is None:
            m.submodules.data_out_fifo = self.data_out_fifo

        line_start_offs = 2285
        with m.FSM("POWERUP"):
            with m.State("POWERUP"):
                with m.If(self.pwr_seq.ready):
                    m.d.sync += [
                        self.init_ctr.eq(0)
                    ]
                    m.next = "INIT"
            with m.State("INIT"):
                m.d.sync += [
                    self.init_ctr.eq(self.init_ctr + 1)
                ]
                with m.If(self.init_ctr == 16):
                    m.next = "SEND-CMD"
                    m.d.sync += [
                        self.init_ctr.eq(0)
                    ]
            with m.State("SEND-CMD"):
                m.d.sync += [
                    cmd_fifo.w_data.eq(self.cmd_words[self.cmd_word_ctr]),
                    cmd_fifo.w_en.eq(1),
                ]
                m.next = "SEND-CMD-W0"
            with m.State("SEND-CMD-W0"):
                m.d.sync += [
                    cmd_fifo.w_en.eq(0),
                ]
                m.next = "SEND-CMD-INCR"
            with m.State("SEND-CMD-INCR"):
                with m.If(self.cmd_word_ctr == len(self.cmd_words)):
                    m.next = "WAIT-FRAME-START"
                    m.d.sync += [
                        self.line_start_ctr.eq(0)
                    ]
                with m.Else():
                    m.d.sync += [
                        self.cmd_word_ctr.eq(self.cmd_word_ctr + 1)
                    ]
                    m.next = "SEND-CMD"
            with m.State("WAIT-FRAME-START"):
                # wait for command transfer to finish
                with m.If(self.cmd.done):
                    m.d.sync += [
                        self.line_start_ctr.eq(self.line_start_ctr + 1),
                        self.line_clk_ctr.eq(0)
                    ]
                cmd_to_line_start_cyc = 668 * 7 + 1
                with m.If(self.line_start_ctr >= cmd_to_line_start_cyc):
                    m.next = "READ-LINE"
                    m.d.sync += [
                        self.line_start_ctr.eq(0)
                    ]
                with m.If(self.line_start_ctr >= (cmd_to_line_start_cyc - self.bias_to_latch_cyc)):
                    m.d.sync += [
                        self.latch_bias.eq(1)
                    ]
            with m.State("READ-LINE"):
                # latch the input FIFO
                m.d.sync += [
                    self.acq.latch.eq(1)
                ]
                m.d.sync += [
                    self.line_clk_ctr.eq(self.line_clk_ctr + 1),
                ]
                with m.If(self.line_clk_ctr == 339 * 7):
                    m.d.sync += [
                        self.line_start_ctr.eq(0),
                        self.row_ctr.eq(self.row_ctr + 1)
                    ]
                    with m.If(self.row_ctr == 261):
                        m.d.sync += [
                            self.row_ctr.eq(0),
                            self.cmd_word_ctr.eq(0),
                            self.line_start_ctr.eq(0),
                            self.acq.latch.eq(0)
                        ]
                        m.next = "INTER-FRAME"
                    with m.Else():
                        m.next = "WAIT-LINE"
                        m.d.sync += [
                            self.acq.latch.eq(0)
                        ]
            with m.State("WAIT-LINE"):
                m.d.sync += [
                    self.line_start_ctr.eq(self.line_start_ctr + 1),
                    self.line_clk_ctr.eq(0)
                ]
                with m.If(self.line_start_ctr == (line_start_offs - self.bias_to_latch_cyc)):
                    m.d.sync += [
                        self.latch_bias.eq(1)
                    ]
                with m.If(self.line_start_ctr == line_start_offs):
                    m.next = "READ-LINE"
            with m.State("INTER-FRAME"):
                m.d.sync += [
                    self.line_start_ctr.eq(self.line_start_ctr + 1),
                ]
                with m.If(self.line_start_ctr == (339 * 7 + line_start_offs)):
                    m.d.sync += [
                        self.line_start_ctr.eq(0)
                    ]
                    m.next = "INIT"

        with m.If(self.latch_bias):
            # start feeding bias values
            b_ctr = Signal(1, reset=0)
            with m.If((b_ctr == 0) & bias_fifo.w_rdy):
                m.d.sync += [
                    bias_fifo.w_data.eq(self.bias_value),
                    bias_fifo.w_en.eq(1),
                    b_ctr.eq(b_ctr + 1)
                ]
            with m.Elif(b_ctr == 1):
                m.d.sync += [
                    bias_fifo.w_en.eq(0),
                    b_ctr.eq(0),
                    self.bias_ctr.eq(self.bias_ctr + 1)
                ]
            with m.If(self.bias_ctr == 338):
                m.d.sync += [
                    self.latch_bias.eq(0),
                    self.bias_ctr.eq(0)
                ]


        return m


if __name__ == "__main__":
    from nmigen.sim import *
    sim_freq = 1e5
    out_fifo = SyncFIFO(width=8, depth=32)
    dut = ISC0901B0Main(pads=None, data_out_fifo=out_fifo, sensor_clk_freq=sim_freq)
    sim = Simulator(dut)

    def proc():

        yield dut.acq.input.eq(0b00)
        for i in range(6837):
            yield

        for i in range(7):
            yield dut.acq.input.eq(0b11)
            yield
            yield dut.acq.input.eq(0b00)
            yield

        for i in range(int(sim_freq * 15)):
            yield



    sim.add_clock(1/dut.sensor_clk_freq)

    sim.add_sync_process(proc)
    with sim.write_vcd("main-dump.vcd", "main-dump.gtkw"):
        sim.run()

