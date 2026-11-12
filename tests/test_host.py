from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))
sys.path.insert(0, str(ROOT / "scripts"))

import bf16_host as host  # noqa: E402
import gate  # noqa: E402


class HostModelTests(unittest.TestCase):
    def test_fma_rounds_once_at_nearest_even(self) -> None:
        one = host.bits(1.0)
        tiny = 0x33800000  # 2^-24: exactly half an ulp above 1.0.
        self.assertEqual(one, host.fma(tiny, one, one))
        self.assertEqual(0x3F800001, host.fma(0x33C00000, one, one))

    def test_fma_handles_subnormals_and_signed_zero(self) -> None:
        one = host.bits(1.0)
        half = host.bits(0.5)
        self.assertEqual(0x00000001, host.fma(0x00000001, one, 0))
        self.assertEqual(0x00000000, host.fma(0x00000001, half, 0))
        self.assertEqual(0x00000000, host.fma(one, one, host.bits(-1.0)))
        self.assertEqual(0x80000000, host.fma(0x80000000, one, 0x80000000))

    def test_bf16_rounds_to_even_on_the_upper_half(self) -> None:
        self.assertEqual(0x3F800000, host.bf16(0x3F808000))
        self.assertEqual(0x3F820000, host.bf16(0x3F818000))
        self.assertEqual(0x3F810000, host.bf16(0x3F810000))

    def test_reference_matches_a_hand_product(self) -> None:
        two_identity = [
            host.bits(2.0) if i % 9 == 0 else 0 for i in range(host.ELEMENTS)
        ]
        b = [host.bits(1 + i / 128) for i in range(host.ELEMENTS)]
        expected = [0x40000000 + (i << 16) for i in range(host.ELEMENTS)]
        self.assertEqual(expected, host.reference(two_identity, b))

    def test_scan_packing_applies_measured_skew(self) -> None:
        packed = host.pack_scan([0, 1 << 60, 0])
        self.assertEqual(1 << (64 + 60 - host.TDI_SKEW_BITS), packed)

    def test_word_layout_matches_rtl(self) -> None:
        source = (ROOT / "rtl" / "tile_host.sv").read_text(encoding="utf-8")
        for name, opcode in (
            ("WRITE", 1),
            ("READ", 2),
            ("START", 3),
            ("STATUS", 4),
            ("DISPLAY", 5),
        ):
            with self.subTest(op=name):
                self.assertTrue(re.search(rf"OP_{name} = 4'd{opcode};", source))
        self.assertIn("write_enable <= command[55:53]", source)
        self.assertIn("host_bank <= command[52]", source)
        self.assertIn("write_addr <= command[45:40]", source)
        self.assertEqual(
            0b101 << 53 | 1 << 60 | 1 << 52 | 9 << 40 | 7,
            host.write_word(0b101, 1, 9, 7),
        )


class GateTests(unittest.TestCase):
    def test_timing_fails_any_negative_corner(self) -> None:
        self.assertEqual(
            0.17, gate.worst_slack("; Worst-case Slack ; 2.67 ; 0.17 ; N/A ; 1.5 ;")
        )
        self.assertEqual(
            -1.3, gate.worst_slack("; Worst-case Slack ; -1.3 ; 0.17 ; N/A ; 1.5 ;")
        )
        self.assertIsNone(gate.worst_slack("no summary"))

    def test_pin_gate_rejects_wrong_location_or_voltage(self) -> None:
        qsf = (
            "set_location_assignment PIN_V16 -to LEDR[0]\n"
            'set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to LEDR[0]\n'
        )
        good = "LEDR[0]   : V16  : output : 3.3-V LVTTL   :    : 4A : Y\n"
        moved = "LEDR[0]   : B8   : output : 3.3-V LVTTL   :    : 4A : N\n"
        wrong_voltage = "LEDR[0]   : V16  : output : 2.5 V   :    : 4A : Y\n"
        self.assertEqual([], gate.pin_errors(qsf, good))
        self.assertEqual(1, len(gate.pin_errors(qsf, moved)))
        self.assertEqual(1, len(gate.pin_errors(qsf, wrong_voltage)))
        self.assertTrue(gate.pin_errors("", good))

    def test_qsf_pin_targets_have_no_braces(self) -> None:
        # The QSF reader keeps braces literally, which silently drops the assignment.
        qsf = (ROOT / "quartus" / "bf16.qsf").read_text(encoding="utf-8")
        self.assertNotIn("{", qsf)
        self.assertEqual(57, qsf.count("set_location_assignment"))
        self.assertEqual(57, qsf.count("-name IO_STANDARD"))


if __name__ == "__main__":
    unittest.main()
