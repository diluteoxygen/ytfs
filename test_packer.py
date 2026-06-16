# test_packer.py
import os, pytest
from packer import pack_video, unpack_video

PASS = "test_super_secret"

def test_roundtrip_and_small_file(tmp_path):
    src = tmp_path / "in.txt"
    vid = tmp_path / "out.mp4"
    restored = tmp_path / "restored.txt"
    
    original_data = os.urandom(1024 * 15) # 15kb noise
    src.write_bytes(original_data)
    
    pack_video(src, vid, PASS)
    assert vid.exists()
    
    unpack_video(vid, restored, PASS)
    assert restored.read_bytes() == original_data

def test_wrong_password(tmp_path):
    src, vid, restored = tmp_path / "in", tmp_path / "vid.mp4", tmp_path / "out"
    src.write_bytes(b"data")
    pack_video(src, vid, PASS)
    
    with pytest.raises(ValueError, match="Incorrect password"):
        unpack_video(vid, restored, "wrong_password")

def test_empty_file(tmp_path):
    src, vid = tmp_path / "empty", tmp_path / "vid.mp4"
    src.touch()
    with pytest.raises(ValueError, match="empty"):
        pack_video(src, vid, PASS)

def test_corrupted_video(tmp_path):
    vid, restored = tmp_path / "vid.mp4", tmp_path / "out"
    vid.write_bytes(os.urandom(1024)) # fake video
    with pytest.raises(Exception): # imageio will throw trying to read garbage
        unpack_video(vid, restored, PASS)