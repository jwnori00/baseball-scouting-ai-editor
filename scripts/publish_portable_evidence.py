"""CI-only append-only evidence branch; never writes main or handles raw media."""
import json
import os
from pathlib import Path
import shutil
import subprocess


def git(*args,check=True):return subprocess.run(['git',*args],check=check,capture_output=True,text=True)


def main():
    if os.environ.get('GITHUB_ACTIONS')!='true':raise RuntimeError('CI only')
    source=Path(os.environ['EVIDENCE_PATH'])
    branch=os.environ.get('EVIDENCE_BRANCH','ci/portable-evidence')
    if branch not in ('ci/portable-evidence','ci/synthetic-evidence'):raise ValueError('Unsupported evidence branch')
    fetched=git('fetch','origin',f'refs/heads/{branch}',check=False)
    if fetched.returncode==0:git('checkout','-B',branch,'FETCH_HEAD')
    else:
        if git('ls-remote','--exit-code','origin',f'refs/heads/{branch}',check=False).returncode!=2:
            raise RuntimeError('Cannot establish missing evidence branch; refusing replacement')
        git('checkout','--orphan',branch);git('rm','-rf','.')
    target=Path('runs')/os.environ['GITHUB_RUN_ID'];target.mkdir(parents=True,exist_ok=True)
    outcome=dict(result=os.environ['BUILD_RESULT'],commit=os.environ['GITHUB_SHA'],
        run_url=f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}",
        artifact_url=os.environ.get('ARTIFACT_URL',''),sources_url=os.environ.get('SOURCES_URL',''),pr_url=os.environ.get('PR_URL',''),pr_error=os.environ.get('PR_ERROR',''))
    for item in source.glob('*'):
        if item.is_file() and item.suffix in ('.xml','.json','.log'):
            # Only synthetic test/build outputs. Bound log size and preserve tail.
            data=item.read_bytes()
            (target/item.name).write_bytes(data[-200_000:])
    (target/'result.json').write_text(json.dumps(outcome,indent=2),encoding='utf-8')
    git('config','user.name','github-actions[bot]');git('config','user.email','41898282+github-actions[bot]@users.noreply.github.com')
    git('add','runs');git('commit','-m',('Record synthetic test outcome ' if branch=='ci/synthetic-evidence' else 'Record Windows portable build ')+os.environ['GITHUB_RUN_ID'])
    git('push','origin',f'HEAD:refs/heads/{branch}')


if __name__=='__main__':main()
