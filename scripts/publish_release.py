"""Public Action: reassemble Git-safe chunks and atomically publish a release."""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import base64
import shutil
import tempfile

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root/'modpack.json').read_text())
tag = 'pack-'+manifest['id'][:16]
repo = 'YukiiSZ/Conmine-downloads'
if not re.fullmatch(r'pack-[0-9a-f]{16}',tag): raise ValueError('Invalid pack id')
result = subprocess.run(['gh','release','view',tag,'--repo',repo,'--json','isDraft'],capture_output=True,text=True)
published = result.returncode == 0 and not json.loads(result.stdout)['isDraft']
out = root/'release'; out.mkdir(exist_ok=True)
for item in manifest['files']:
    name = item['fileName']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]*\.jar',name): raise ValueError('Invalid file name')
    target = out/name
    with target.open('wb') as stream:
        parts = sorted((root/'parts').glob(name+'.*.part'))
        if not parts: raise ValueError('Missing file chunks')
        for index,part in enumerate(parts):
            if part.name != f'{name}.{index:04}.part': raise ValueError('Non-contiguous chunk list')
            with part.open('rb') as source:
                while block := source.read(1024*1024): stream.write(block)
    with target.open('rb') as stream: actual = hashlib.file_digest(stream,'sha256').hexdigest()
    if target.stat().st_size != item['size'] or actual != item['sha256']: raise ValueError('File integrity mismatch')
(out/'modpack.json').write_bytes((root/'modpack.json').read_bytes())
(out/'THIRD_PARTY_MODS.txt').write_bytes((root/'THIRD_PARTY_MODS.txt').read_bytes())

# Keep binary transport chunks out of the permanent default branch and release tags.
# This token belongs only to this PUBLIC repository; it cannot read the private source.
with tempfile.TemporaryDirectory(prefix='conmine-public-metadata-') as directory:
    clean = Path(directory)
    for name in ['README.md','modpack.json','THIRD_PARTY_MODS.txt','scripts/publish_release.py','.github/workflows/release.yml']:
        destination = clean/name; destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(root/name,destination)
    def git(*args,**kw): return subprocess.run(['git',*args],cwd=clean,check=True,**kw)
    git('init','-b','main')
    git('config','user.name','github-actions[bot]')
    git('config','user.email','41898282+github-actions[bot]@users.noreply.github.com')
    git('add','.')
    git('commit','-m','Published modpack metadata '+manifest['id'][:16])
    commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd=clean,text=True).strip()
    token = os.environ['GH_TOKEN']
    encoded = base64.b64encode(('x-access-token:'+token).encode()).decode()
    env = dict(os.environ,GIT_CONFIG_COUNT='1',GIT_CONFIG_KEY_0='http.https://github.com/.extraheader',GIT_CONFIG_VALUE_0='AUTHORIZATION: basic '+encoded)
    git('remote','add','origin','https://github.com/'+repo+'.git')
    git('push','--force','origin','HEAD:main',env=env)
    if published:
        git('push','--force','origin','HEAD:refs/tags/'+tag,env=env)

if published:
    print('Verified immutable pack assets already exist; public staging cleaned.'); raise SystemExit(0)
if result.returncode != 0:
    subprocess.run(['gh','release','create',tag,'--repo',repo,'--target',commit,'--draft','--title','Conmine modpack '+manifest['id'][:12],'--notes','Minecraft 1.21.1 / NeoForge. Mods retain their original licenses; see THIRD_PARTY_MODS.txt.'],check=True)
subprocess.run(['gh','release','upload',tag,'--repo',repo,'--clobber',*[str(p) for p in out.iterdir()]],check=True)
subprocess.run(['gh','release','edit',tag,'--repo',repo,'--draft=false','--latest'],check=True)
print('Release published: '+tag)
