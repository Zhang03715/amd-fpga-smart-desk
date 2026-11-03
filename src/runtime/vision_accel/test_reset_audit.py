import tempfile
from pathlib import Path
import unittest
from .reset_audit import audit_handoff


class ResetAuditTests(unittest.TestCase):
    def check(self,polarity):
        xml='''<SYSTEM><MODULE INSTANCE="zero" MODTYPE="xlconstant"><PARAMETERS>
        <PARAMETER NAME="CONST_VAL" VALUE="0x0"/></PARAMETERS></MODULE>
        <MODULE INSTANCE="reset" MODTYPE="proc_sys_reset"><PARAMETERS>
        <PARAMETER NAME="C_AUX_RESET_HIGH" VALUE="%d"/>
        <PARAMETER NAME="C_EXT_RESET_HIGH" VALUE="0"/></PARAMETERS><PORTS>
        <PORT NAME="aux_reset_in"><CONNECTIONS><CONNECTION INSTANCE="zero" PORT="dout"/>
        </CONNECTIONS></PORT><PORT NAME="ext_reset_in"/><PORT NAME="mb_debug_sys_rst"/>
        <PORT NAME="dcm_locked"/></PORTS></MODULE></SYSTEM>''' % polarity
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'design.hwh';p.write_text(xml)
            return audit_handoff(p)
    def test_active_low_tied_zero_is_rejected(self):
        self.assertFalse(self.check(0)['passed'])
    def test_active_high_tied_zero_is_inactive(self):
        self.assertTrue(self.check(1)['passed'])
