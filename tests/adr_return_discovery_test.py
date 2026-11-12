"""Regression checks for ADR callback discovery at AArch64 function returns."""
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'recomp'))
import gen

BASE = 0x1000
NOP = 0xD503201F
BR_X1 = 0xD61F0020
ADD_X0_X0_X1 = 0x8B010000
RETURNS = (0xD65F03C0, 0xD65F0BFF, 0xD65F0FFF)


def adr_x0(byte_offset):
    return 0x10000000 | ((byte_offset & 3) << 29) | (((byte_offset >> 2) & 0x7FFFF) << 5)


class FakeModule:
    lo = BASE
    hi = BASE + 40

    def __init__(self, middle):
        words = [adr_x0(32), *middle]
        self.words = np.array((words + [NOP] * 8)[:8] + [RETURNS[0], NOP], dtype=np.uint32)

    def seeds(self):
        return [self.lo]


class ReturnBoundaryDiscovery(unittest.TestCase):
    def discovered(self, middle):
        return 8 in gen.discover(FakeModule(middle))[0]

    def test_callback_before_return_and_next_indirect_branch(self):
        for ret in RETURNS:
            with self.subTest(ret=hex(ret)):
                self.assertTrue(self.discovered([ret, BR_X1]))

    def test_next_function_add_is_not_part_of_prior_adr(self):
        for ret in RETURNS:
            with self.subTest(ret=hex(ret)):
                self.assertTrue(self.discovered([ret, ADD_X0_X0_X1, BR_X1]))

    def test_jump_table_branch_before_return_is_not_callback(self):
        self.assertFalse(self.discovered([BR_X1, RETURNS[0]]))

    def test_jump_table_add_before_return_is_not_callback(self):
        self.assertFalse(self.discovered([ADD_X0_X0_X1, RETURNS[0], BR_X1]))


if __name__ == '__main__':
    unittest.main()
