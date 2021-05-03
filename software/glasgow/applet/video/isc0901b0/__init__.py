import logging
from nmigen import *
from nmigen.hdl.cd import ClockDomain
from nmigen.hdl.rec import Record
from nmigen.hdl.xfrm import DomainRenamer
from nmigen.build import Platform
from ....gateware.pads import *
from ....gateware.pll import *
from ... import *
from .top import ISC0901B0Subtarget


class ISC0901B0InputApplet(GlasgowApplet, name="isc0901b0"):
    logger = logging.getLogger(__name__)
    help = "Capture images from ISC0901B0 thermal image sensor (e.g. Autoliv NV3)"
    description = """
    
    """

    __pins = ("ena", "clk", "cmd", "bias", "data_odd", "data_even", "en_3v3", "en_2v5",
              "d0", "d1", "d2", "d3", "d4", "d5", "d6", "d7")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        for pin in cls.__pins:
            access.add_pin_argument(parser, pin, default=True)

    def build(self, target, args, test_pattern=True):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = iface.add_subtarget(ISC0901B0Subtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            in_fifo=iface.get_in_fifo(depth=4096, auto_flush=False)
        ))
        return subtarget

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args, pull_low=
            set([i for i in range(len(self.__pins))]))

        got_frame = False
        num_tries = 10
        w = 364
        h = 266
        num_frames = 5
        for i in range(num_tries):
            data = (await iface.read(w * h * num_frames * 2))
            if data[0] == 0x55 and data[1] == 0x15:
                got_frame = True
            else:
                print("resetting")
                await iface.reset()

        if not got_frame:
            print("failed")
            return

        import numpy as np
        import matplotlib.pyplot as plt
        img = np.ndarray(shape=(h, w), dtype="<u2", buffer=data)
        #plt.imshow(img)
        #plt.show(True)
        data_ctr = 0
        f = open("frame.bin", "wb")
        f.write(data)

        i = 0
        for frame in range(num_frames):
            txt = ""
            for i in range(16):
                txt += "%02X, " % data[i + frame * w * h * 2]
            print(txt)
        #while i < (len(data) // 2):
        #    if i % 8 == 0:
        #        txt += "\n%06X: " % data_ctr
        #    w = data[i*2+1] << 8 | data[i*2]
        #    txt += "%04x " % w
        #    i += 1
        #    data_ctr += 1
        f.close()

# -------------------------------------------------------------------------------------------------

class ISC0901B0TestCase(GlasgowAppletTestCase, applet=ISC0901B0InputApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--port", "AB"])


