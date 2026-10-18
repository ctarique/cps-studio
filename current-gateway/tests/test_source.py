import unittest
from gateway.source import prepare,SourceError
class SourceTests(unittest.TestCase):
    def test_valid_program(self):
        p=prepare("void experiment() { led(1); wait_ms(200); led(0); status(); }")
        self.assertEqual(p["bytecode"],"L1,W200,L0,S0");self.assertEqual(p["duration_ms"],200)
    def test_status_only(self):self.assertFalse(prepare("void experiment(){status();}")["uses_led"])
    def test_boundary_limits(self):
        s="void experiment(){"+("wait_ms(1000);"*5)+("status();"*27)+"}"
        self.assertEqual(prepare(s)["steps"],32)
    def test_source_rejections(self):
        bad=[None,{}, "", "x"*2049,"void experiment(){лed(0);}",
             "#include <WiFi.h>\nvoid experiment(){status();}",
             "void experiment(){system(1);}","void experiment(){while(1){};}",
             "void experiment(){led(1);}","void experiment(){led(2);}",
             "void experiment(){wait_ms(9);}","void experiment(){wait_ms(1001);}",
             "void experiment(){wait_ms(010);}","void experiment(){status(0);}",
             "void experiment(){}","void experiment(){/*secret*/status();}",
             "void experiment(){status();} void setup(){}",
             "void experiment(){"+("wait_ms(1000);"*6)+"}",
             "void experiment(){"+("status();"*33)+"}",
             "void experiment(){led(-1);}","void experiment(){status();}\x00"]
        for s in bad:
            with self.subTest(source_kind=type(s).__name__):
                with self.assertRaises(SourceError):prepare(s)
