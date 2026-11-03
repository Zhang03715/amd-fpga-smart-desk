"""Prepare local aliases/manifest includes without changing vendor sources."""
from pathlib import Path
import subprocess
import yaml
workspace=Path(__file__).resolve().parents[2]
source=workspace/'firmware/xiaozhi-amd/managed_components'
links=workspace/'.build-tools/idf-offline';links.mkdir(parents=True,exist_ok=True)
names={p.name.split('__')[-1]:p for p in source.iterdir() if (p/'CMakeLists.txt').exists()}
for name,p in names.items():
    dest=links/name
    if dest.exists():
        if dest.resolve()!=p.resolve():raise RuntimeError('unexpected existing alias '+str(dest))
    else:
        # All paths come from the verified workspace, not input from the network.
        def quote(s):return "'"+str(s).replace("'","''")+"'"
        subprocess.run(['powershell','-NoProfile','-Command',f'New-Item -ItemType Junction -Path {quote(dest)} -Target {quote(p)} | Out-Null'],check=True)
lines=['# Generated from installed component manifests; sources remain unchanged.']
for name,p in names.items():
    manifest=p/'idf_component.yml'
    if not manifest.exists():continue
    for dep in (yaml.safe_load(manifest.read_text(encoding='utf-8')) or {}).get('dependencies',{}):
        short=dep.split('/')[-1]
        if short not in names or short==name:continue
        lines.extend([f'idf_component_get_property(offline_lib "{name}" COMPONENT_LIB)',f'idf_component_get_property(offline_dep "{short}" COMPONENT_LIB)',
            'if(TARGET ${offline_lib} AND TARGET ${offline_dep})','    get_target_property(offline_type ${offline_lib} TYPE)',
            '    if(offline_type STREQUAL "INTERFACE_LIBRARY")',
            '        target_include_directories(${offline_lib} INTERFACE $<TARGET_PROPERTY:${offline_dep},INTERFACE_INCLUDE_DIRECTORIES>)',
            '    else()',
            '        target_include_directories(${offline_lib} PUBLIC $<TARGET_PROPERTY:${offline_dep},INTERFACE_INCLUDE_DIRECTORIES>)',
            '    endif()','endif()'])
(workspace/'.build-tools/offline-deps.cmake').write_text('\n'.join(lines),encoding='utf-8')
print('OFFLINE_ALIASES_READY',len(names))
