import os
import pytest
from pathlib import Path
from typer.testing import CliRunner
from ytfs import app

runner = CliRunner()
PASS = "test_super_secret"

def test_roundtrip_and_small_file(tmp_path, monkeypatch):
    # Change working directory to tmp_path so Output/ gets created there
    monkeypatch.chdir(tmp_path)
    
    src = tmp_path / "in.txt"
    original_data = os.urandom(1024 * 15) # 15kb noise
    src.write_bytes(original_data)
    
    result = runner.invoke(app, ["pack", str(src), "--password", PASS, "--yes"])
    assert result.exit_code == 0
    assert "Success!" in result.stdout
    
    vid = Path("Output/Packed/in.txt.mp4")
    assert vid.exists()
    
    # Inspect
    res_inspect = runner.invoke(app, ["inspect", str(vid)])
    assert res_inspect.exit_code == 0
    assert "in.txt" in res_inspect.stdout
    
    # Verify
    res_verify = runner.invoke(app, ["verify", str(vid), "--password", PASS])
    assert res_verify.exit_code == 0
    assert "Verification successful" in res_verify.stdout
    
    # Unpack
    res_unpack = runner.invoke(app, ["unpack", str(vid), "--password", PASS])
    assert res_unpack.exit_code == 0
    
    restored = Path("Output/Unpacked/in.txt")
    assert restored.exists()
    assert restored.read_bytes() == original_data

def test_wrong_password(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "in.txt"
    src.write_bytes(b"data")
    
    runner.invoke(app, ["pack", str(src), "--password", PASS, "--yes"])
    vid = Path("Output/Packed/in.txt.mp4")
    
    result = runner.invoke(app, ["unpack", str(vid), "--password", "wrong_password"])
    assert result.exit_code == 1
    assert "Incorrect password" in result.stdout

def test_empty_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "empty"
    src.touch()
    result = runner.invoke(app, ["pack", str(src), "--password", PASS, "--yes"])
    assert result.exit_code == 1
    assert "empty" in result.stdout

def test_corrupted_video(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    vid = tmp_path / "vid.mp4"
    vid.write_bytes(os.urandom(1024)) # fake video
    
    result = runner.invoke(app, ["unpack", str(vid), "--password", PASS])
    assert result.exit_code == 1

def test_folder_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    
    # Create a dummy folder with some contents
    dir_to_pack = tmp_path / "my_folder"
    dir_to_pack.mkdir()
    (dir_to_pack / "file1.txt").write_text("Hello from file 1")
    (dir_to_pack / "subdir").mkdir()
    (dir_to_pack / "subdir" / "file2.txt").write_text("Hello from file 2")
    
    result = runner.invoke(app, ["pack", str(dir_to_pack), "--password", PASS, "--yes"])
    assert result.exit_code == 0
    assert "Directory detected" in result.stdout
    
    vid = Path("Output/Packed/my_folder.mp4")
    assert vid.exists()
    
    # Unpack it
    res_unpack = runner.invoke(app, ["unpack", str(vid), "--password", PASS])
    assert res_unpack.exit_code == 0
    
    restored_dir = Path("Output/Unpacked/my_folder")
    assert restored_dir.exists()
    assert restored_dir.is_dir()
    assert (restored_dir / "file1.txt").read_text() == "Hello from file 1"
    assert (restored_dir / "subdir" / "file2.txt").read_text() == "Hello from file 2"