from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).with_name('sync_product_ui.py')))
import subprocess,zipfile,shutil
root=Path(__file__).resolve().parents[1]; workspace=root.parent
jdk=Path('D:/soft/study/cubeMX/jre/bin');sdk=workspace/'.build-tools/android'
jar=next((sdk/'platform').rglob('android.jar'));bt=next((sdk/'build-tools').rglob('aapt2.exe')).parent
build=root/'android/build';build.mkdir(exist_ok=True);classes=build/'classes';classes.mkdir(exist_ok=True)
def run(args):subprocess.run([str(x) for x in args],check=True)
run([bt/'aapt2.exe','compile','--dir',root/'android/res','-o',build/'resources.zip'])
run([bt/'aapt2.exe','link','-o',build/'base.apk','-I',jar,'--manifest',root/'android/AndroidManifest.xml',build/'resources.zip','-A',root/'web'])
run([jdk/'javac.exe','--release','8','-encoding','UTF-8','-classpath',jar,'-d',classes,*sorted((root/'android/src').rglob('*.java'))])
dex=build/'dex';dex.mkdir(exist_ok=True)
run([jdk/'java.exe','-cp',bt/'lib/d8.jar','com.android.tools.r8.D8','--lib',jar,'--min-api','26','--output',dex,*sorted(classes.rglob('*.class'))])
shutil.copy2(build/'base.apk',build/'unsigned.apk')
with zipfile.ZipFile(build/'unsigned.apk','a',zipfile.ZIP_DEFLATED) as z:z.write(dex/'classes.dex','classes.dex')
run([bt/'zipalign.exe','-f','4',build/'unsigned.apk',build/'aligned.apk'])
key=build/'test-signing.p12'
if not key.exists():run([jdk/'keytool.exe','-genkeypair','-keystore',key,'-storepass','android','-keypass','android','-alias','deskhub','-dname','CN=Desk Hub Local Test','-keyalg','RSA','-keysize','2048','-validity','3650'])
out=root/'dist/DeskHub-test.apk'
run([jdk/'java.exe','-jar',bt/'lib/apksigner.jar','sign','--ks',key,'--ks-key-alias','deskhub','--ks-pass','pass:android','--key-pass','pass:android','--out',out,build/'aligned.apk'])
run([jdk/'java.exe','-jar',bt/'lib/apksigner.jar','verify','--verbose',out])
print('APK_READY',out)
