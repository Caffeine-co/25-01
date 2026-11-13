"""制作不包含私密 data/、缓存和密钥的正式发行包，并生成 SHA256 清单。"""
from __future__ import annotations
import hashlib
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT.parents[1]/'WorldLife-2.0.0-Release.zip'
PREFIX='WorldLife-2.0.0'
INCLUDE=['README.md','pyproject.toml','.gitignore','docs','simlife','scripts','tests','examples','results']
SKIP_PARTS={'__pycache__','.git','.venv','.pytest_cache','data', 'dist'}
SKIP_SUFFIXES={'.pyc','.pyo','.egg-info','.db-wal','.db-shm'}


def all_files():
    files=[]
    for item in INCLUDE:
        p=ROOT/item
        for f in ([p] if p.is_file() else p.rglob('*')):
            if not f.is_file() or any(part in SKIP_PARTS or part.endswith('.egg-info')
                                      for part in f.relative_to(ROOT).parts):
                continue
            if f.suffix in SKIP_SUFFIXES or f.name.endswith(('.db-wal','.db-shm')):
                continue
            files.append(f)
    return sorted(set(files))


def main():
    files=all_files()
    assert len(files)>75
    hashes=[]
    for f in files:
        rel=f.relative_to(ROOT).as_posix()
        sha=hashlib.sha256(f.read_bytes()).hexdigest()
        hashes.append(f'{sha}  {rel}')
    manifest='\n'.join(hashes)+'\n'
    (ROOT/'MANIFEST.sha256').write_text(manifest,encoding='utf-8')
    with zipfile.ZipFile(TARGET,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=8) as z:
        for f in files:
            z.write(f,arcname=PREFIX+'/'+f.relative_to(ROOT).as_posix())
        z.writestr(PREFIX+'/MANIFEST.sha256',manifest)
    print('ZIP:',TARGET)
    print('FILES:',len(files)+1)
    print('BYTES:',TARGET.stat().st_size)

if __name__=='__main__':
    main()
