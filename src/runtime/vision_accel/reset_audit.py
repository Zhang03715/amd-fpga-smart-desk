"""Check constant-driven proc_sys_reset inputs in generated HWH metadata."""
import xml.etree.ElementTree as ET


def audit_handoff(path):
    root = ET.parse(path).getroot()
    modules = {m.get('INSTANCE'):m for m in root.findall('.//MODULE')}
    constants = {}
    for name,m in modules.items():
        if m.get('MODTYPE') == 'xlconstant':
            values = {p.get('NAME'):p.get('VALUE') for p in m.findall('./PARAMETERS/PARAMETER')}
            if int(values.get('CONST_WIDTH','1'),0) == 1:
                constants[name] = int(values['CONST_VAL'],0)
    checks = []
    for name,m in modules.items():
        if m.get('MODTYPE') != 'proc_sys_reset':continue
        params = {p.get('NAME'):p.get('VALUE') for p in m.findall('./PARAMETERS/PARAMETER')}
        ports = {p.get('NAME'):p for p in m.findall('./PORTS/PORT')}
        for port, active in [('aux_reset_in',int(params['C_AUX_RESET_HIGH'],0)),
                             ('ext_reset_in',int(params['C_EXT_RESET_HIGH'],0)),
                             ('mb_debug_sys_rst',1),('dcm_locked',0)]:
            for connection in ports[port].findall('./CONNECTIONS/CONNECTION'):
                source = connection.get('INSTANCE')
                if source in constants and connection.get('PORT') == 'dout':
                    value = constants[source]
                    checks.append(dict(module=name,port=port,source=source,value=value,
                                       asserted_level=active,safe=value!=active))
    return dict(scope='Constant reset/lock inputs only; not dynamic reset or AXI validation',
                checks=checks,passed=bool(checks) and all(c['safe'] for c in checks))
