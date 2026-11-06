"""Offline compatibility repair for the private EchoNote runtime only."""
from pathlib import Path
import hashlib, shutil, sys, time, zipfile

ROOT=Path(__file__).resolve().parent
VERSION='80.9.0'
WHEEL_SHA256='062d34222ad13e0cc312a4c02d73f059e86a4acbfbdea8f8f76b28c99f306922'

def pin_file(path):
    if not path.exists():return
    lines=path.read_text('utf-8-sig').splitlines()
    result=[];found=False
    for line in lines:
        if line.strip().lower().startswith('setuptools') and not line.strip().startswith('#'):
            if not found:result.append('setuptools=='+VERSION);found=True
        else:result.append(line)
    if not found:result.append('setuptools=='+VERSION)
    path.write_text('\n'.join(result)+'\n',encoding='utf-8')

def ensure(root=ROOT):
    root=Path(root).resolve()
    target=root/'.runtime'/'Lib'/'site-packages'
    wheel=root/'compat-wheels'/f'setuptools-{VERSION}-py3-none-any.whl'
    if not (root/'run.py').exists() or not (root/'.runtime').is_dir():
        raise RuntimeError('This is not the EchoNote application folder.')
    if not wheel.exists() or hashlib.sha256(wheel.read_bytes()).hexdigest()!=WHEEL_SHA256:
        raise RuntimeError('Compatibility wheel is missing or incomplete. Extract the repair package again.')
    target.mkdir(parents=True,exist_ok=True)
    if not (target/'pkg_resources'/'__init__.py').exists() or not (target/f'setuptools-{VERSION}.dist-info').is_dir():
        backup=root/'.repair-backup'/('setuptools-'+str(time.time_ns()))
        backup.mkdir(parents=True,exist_ok=True)
        old=[target/n for n in ('setuptools','pkg_resources','_distutils_hack','distutils-precedence.pth')]
        old+=list(target.glob('setuptools-*.dist-info'))
        moved=[];written=[]
        try:
            for p in old:
                if p.exists():shutil.move(str(p),str(backup/p.name));moved.append(p.name)
            with zipfile.ZipFile(wheel) as z:
                if 'pkg_resources/__init__.py' not in z.namelist():raise RuntimeError('Wheel does not include pkg_resources.')
                for entry in z.infolist():
                    dest=(target/entry.filename).resolve()
                    if not dest.is_relative_to(target.resolve()):raise RuntimeError('Invalid wheel path.')
                    z.extract(entry,target);written.append(dest)
        except BaseException:
            for p in reversed(written):
                if p.is_file():p.unlink(missing_ok=True)
            for name in moved:
                dest=target/name
                if dest.is_dir():shutil.rmtree(dest)
                elif dest.exists():dest.unlink()
                shutil.move(str(backup/name),str(dest))
            raise
        print('Compatibility package restored: setuptools 80.9.0 with pkg_resources.',flush=True)
    for name in ('requirements.txt','requirements-lock-windows.txt'):pin_file(root/name)

if __name__=='__main__':
    try:ensure()
    except Exception as e:print('Compatibility repair failed:',e,flush=True);sys.exit(1)
