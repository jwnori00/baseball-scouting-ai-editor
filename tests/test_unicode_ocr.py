from pathlib import Path
import hashlib
import pytest
from bsae.ingest import ocr_runtime


def test_unicode_language_and_executable_are_staged_without_source_changes(tmp_path,monkeypatch):
    installed=tmp_path/'한글 설치 Martínez';installed.mkdir()
    executable=installed/'tesseract.exe';executable.write_bytes(b'unit executable')
    (installed/'dep.dll').write_bytes(b'unit dependency')
    data=installed/'tessdata';data.mkdir();source=data/'eng.traineddata';source.write_bytes(b'unit language')
    scratch=tmp_path/'ascii-workspace';scratch.mkdir()
    monkeypatch.setattr(ocr_runtime,'_workspace',scratch)
    monkeypatch.setattr(ocr_runtime,'_verified',{})
    monkeypatch.setattr(ocr_runtime,'_tools_verified',{})
    selected,args,environment,cwd=ocr_runtime.prepare(executable,['stdin','stdout','-l','eng','-c','tessedit_create_tsv=1'])
    assert selected.isascii() and cwd.isascii()
    assert Path(selected).read_bytes()==executable.read_bytes()
    assert Path(environment['TESSDATA_PREFIX']).joinpath('eng.traineddata').read_bytes()==source.read_bytes()
    assert (Path(selected).parent/'dep.dll').read_bytes()==b'unit dependency'
    assert source.read_bytes()==b'unit language'
    assert args[0]=='--tessdata-dir'


def test_ocr_language_path_traversal_is_rejected(tmp_path,monkeypatch):
    data=tmp_path/'tessdata';data.mkdir()
    workspace=tmp_path/'runtime';workspace.mkdir()
    monkeypatch.setattr(ocr_runtime,'_workspace',workspace)
    with pytest.raises(ValueError):ocr_runtime.prepare(tmp_path/'tesseract.exe',['stdin','stdout','-l','../secret'])


def test_list_langs_preserves_all_bundled_language_models(tmp_path,monkeypatch):
    from bsae.ingest import ocr_runtime
    install=tmp_path/'한글';data=install/'tessdata';data.mkdir(parents=True)
    executable=install/'tesseract.exe';executable.write_bytes(b'fake-test-tool')
    for language in ('eng','kor','jpn'):(data/(language+'.traineddata')).write_bytes(language.encode())
    workspace=tmp_path/'ascii';workspace.mkdir();monkeypatch.setattr(ocr_runtime,'_workspace',workspace)
    monkeypatch.setattr(ocr_runtime,'_verified',{});monkeypatch.setattr(ocr_runtime,'_tools_verified',{})
    ocr_runtime.prepare(executable,['--list-langs'])
    assert {p.stem for p in (workspace/'tessdata').glob('*.traineddata')}=={'eng','kor','jpn'}
