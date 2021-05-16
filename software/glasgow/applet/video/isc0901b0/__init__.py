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

        w = 338
        h = 259
        num_frames = 60
        data = (await iface.read(w * h * num_frames * 2))
        f = open("frame.bin", "wb")
        f.write(data)
        f.close()
        for frame in range(num_frames):
            txt = ""
            for i in range(16):
                txt += "%02X, " % data[i + frame * w * h * 2]
            print(txt)

        import numpy as np
        import matplotlib.pyplot as plt
        frames = np.ndarray(shape=(num_frames, h, w), dtype="<u2", buffer=data)[:, 3:, 2:]
        img = frames[-1]

        bp_where = np.where(abs(img - np.mean(img)) > 5 * np.std(img))
        print("bad pixels: %d" % len(bp_where[0]))
        img = img.copy()
        img[bp_where] = np.mean(img)

        print("min: %d, max: %d, mean: %.0f, std: %.3f" % (np.min(img), np.max(img), np.mean(img), np.std(img)))

        fig, ax = plt.subplots(1, 2, tight_layout=True)
        ax[0].imshow(img)
        ax[1].hist(img.flatten(), bins="auto")

        plt.show(True)



# -------------------------------------------------------------------------------------------------

class ISC0901B0TestCase(GlasgowAppletTestCase, applet=ISC0901B0InputApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--port", "AB"])


