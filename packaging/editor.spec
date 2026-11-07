from pathlib import Path
import os
root=Path(SPECPATH).parent
assets=Path(os.environ['BSAE_BUILD_ASSETS']).resolve()
binaries=[]
datas=[]
for p in (assets/'tools').rglob('*'):
    if p.is_file():
        target=str(Path('tools')/p.relative_to(assets/'tools').parent)
        (binaries if p.suffix.lower() in ('.exe','.dll') else datas).append((str(p),target))
for folder in (('licenses','models') if os.environ.get('BSAE_BUILD_KIND')=='release' else ('licenses',)):
    datas.append((str(assets/folder),folder))
datas += [(str(root/'profiles'),'profiles'),(str(root/'docs'),'docs'),(str(root/'README.md'),'.'),(str(assets/'build-policy.json'),'.')]
datas += [(str(root/'tests'/'fixtures'/name),'test-fixtures') for name in ('av1-8bit.mp4','av1-10bit.mp4')]
a=Analysis([str(root/'packaging'/'entry.py')],pathex=[str(root/'src')],
    binaries=binaries,datas=datas,hiddenimports=['cv2','numpy'],
    excludes=['pytest','PyQt5','PyQt6','tkinter','torch','torchvision','onnx','onnxruntime'],noarchive=False)
a.binaries=[x for x in a.binaries if not Path(x[0]).name.lower().startswith('opencv_videoio_ffmpeg')]
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='BaseballScoutingAIEditor',console=False,
    debug=False,strip=False,upx=False,contents_directory='_internal')
coll=COLLECT(exe,a.binaries,a.datas,name='BaseballScoutingAIEditor',strip=False,upx=False)
