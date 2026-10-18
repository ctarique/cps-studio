"""Project-adopted source boundaries; software checks, not physical timing tests."""
import unittest
from gateway.source import prepare, SourceError


class SourceBoundaryTests(unittest.TestCase):
    def test_ascii_character_limit_exact_and_one_over(self):
        body = "void experiment(){status();}"
        self.assertEqual(prepare(body + " " * (2048 - len(body)))["bytecode"], "S0")
        with self.assertRaises(SourceError):
            prepare(body + " " * (2049 - len(body)))

    def test_wait_endpoints_and_adjacent_rejections(self):
        for value in (10, 1000):
            with self.subTest(value=value):
                self.assertEqual(prepare(f"void experiment(){{wait_ms({value});}}")["duration_ms"], value)
        for value in (0, 9, 1001):
            with self.subTest(value=value), self.assertRaises(SourceError):
                prepare(f"void experiment(){{wait_ms({value});}}")

    def test_total_wait_limit(self):
        body = "void experiment(){" + "wait_ms(1000);" * 5
        self.assertEqual(prepare(body + "}")["duration_ms"], 5000)
        with self.assertRaises(SourceError):
            prepare(body + "wait_ms(10);}")

    def test_operation_limit_and_final_led_semantics(self):
        self.assertEqual(prepare("void experiment(){" + "status();" * 32 + "}")["steps"], 32)
        with self.assertRaises(SourceError):
            prepare("void experiment(){" + "status();" * 33 + "}")
        self.assertEqual(prepare("void experiment(){led(1);led(0);wait_ms(10);status();}")["bytecode"],
                         "L1,L0,W10,S0")
        with self.assertRaises(SourceError):
            prepare("void experiment(){led(1);status();}")


if __name__ == "__main__":
    unittest.main()
