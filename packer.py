# packer.py
#!/usr/bin/env python3
import os, sys, getpass, base64, argparse
import numpy as np
import imageio
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

BLOCK_SIZE = 8
W_BLOCKS, H_BLOCKS = 1920 // BLOCK_SIZE, 1080 // BLOCK_SIZE
BYTES_PER_FRAME = (W_BLOCKS * H_BLOCKS * 3) // 8

def get_cipher(password: str, salt: bytes) -> Fernet:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=480000)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(password.encode())))

def pack_video(in_path, out_path, password):
    if os.path.getsize(in_path) == 0:
        raise ValueError("Input file is empty.")
        
    with open(in_path, 'rb') as f:
        raw_data = f.read()

    salt = os.urandom(16)
    ciphertext = get_cipher(password, salt).encrypt(raw_data)
    
    payload = salt + len(ciphertext).to_bytes(8, 'big') + ciphertext
    pad_len = BYTES_PER_FRAME - (len(payload) % BYTES_PER_FRAME)
    if pad_len != BYTES_PER_FRAME:
        payload += b'\x00' * pad_len

    bits = np.unpackbits(np.frombuffer(payload, dtype=np.uint8)).reshape(-1, H_BLOCKS, W_BLOCKS, 3)
    writer = imageio.get_writer(out_path, fps=10, macro_block_size=1)
    
    for frame_bits in bits:
        writer.append_data((np.repeat(np.repeat(frame_bits, BLOCK_SIZE, axis=0), BLOCK_SIZE, axis=1) * 255).astype(np.uint8))
    writer.close()

def unpack_video(in_path, out_path, password):
    reader = imageio.get_reader(in_path)
    bits = [(frame[BLOCK_SIZE//2::BLOCK_SIZE, BLOCK_SIZE//2::BLOCK_SIZE, :] > 127).astype(np.uint8).flatten() for frame in reader]
    reader.close()

    extracted_bytes = np.packbits(np.concatenate(bits)).tobytes()
    salt = extracted_bytes[:16]
    expected_len = int.from_bytes(extracted_bytes[16:24], 'big')
    ciphertext = extracted_bytes[24 : 24 + expected_len]

    try:
        raw_data = get_cipher(password, salt).decrypt(ciphertext)
    except InvalidToken:
        raise ValueError("Incorrect password or corrupted video.")

    with open(out_path, 'wb') as f:
        f.write(raw_data)

def main():
    parser = argparse.ArgumentParser(description="Pack/Unpack files to encrypted video.")
    parser.add_argument("mode", choices=["pack", "unpack"])
    parser.add_argument("input", help="Input file path")
    parser.add_argument("output", help="Output file path")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        sys.exit(f"Error: Input file '{args.input}' not found.")

    pwd = os.environ.get("PACKER_PASS") or getpass.getpass(f"Enter password to {args.mode}: ")
    if args.mode == "pack" and not os.environ.get("PACKER_PASS"):
        if pwd != getpass.getpass("Confirm password: "): sys.exit("Passwords don't match.")

    try:
        if args.mode == "pack":
            pack_video(args.input, args.output, pwd)
        else:
            unpack_video(args.input, args.output, pwd)
        print(f"Success: {args.mode} complete -> {args.output}")
    except Exception as e:
        sys.exit(f"Error: {str(e)}")

if __name__ == "__main__":
    main()