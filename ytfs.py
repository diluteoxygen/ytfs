#!/usr/bin/env python3
import os
import sys
import getpass
import base64
import json
import time
import shutil
import tempfile
import typer
import questionary
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn, BarColumn, TextColumn
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from rich import print as rprint

import numpy as np
import imageio
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

app = typer.Typer(help="YTFS: File <-> Video Storage CLI", add_completion=False, invoke_without_command=True)
console = Console()

BLOCK_SIZE = 8
W_BLOCKS, H_BLOCKS = 1920 // BLOCK_SIZE, 1080 // BLOCK_SIZE
BYTES_PER_FRAME = (W_BLOCKS * H_BLOCKS * 3) // 8
MAGIC_BYTES = b"YTFS"

def _lerp(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> str:
    """Linear-interpolate two RGB colours; return a Rich colour string."""
    r = int(c1[0] + (c2[0] - c1[0]) * t)
    g = int(c1[1] + (c2[1] - c1[1]) * t)
    b = int(c1[2] + (c2[2] - c1[2]) * t)
    return f"rgb({r},{g},{b})"

def print_banner():
    # Pre-computed ASCII art for "YTFS" (font: ansi_shadow) to keep code dependency-free
    lines = [
        "██╗   ██╗████████╗███████╗███████╗",
        "╚██╗ ██╔╝╚══██╔══╝██╔════╝██╔════╝",
        " ╚████╔╝    ██║   █████╗  ███████╗",
        "  ╚██╔╝     ██║   ██╔══╝  ╚════██║",
        "   ██║      ██║   ██║     ███████║",
        "   ╚═╝      ╚═╝   ╚═╝     ╚══════╝"
    ]
    
    n = len(lines)
    C1 = (100, 48, 224)   # #6430E0
    C2 = (188, 132, 255)  # #BC84FF

    art = Text(no_wrap=True)
    for i, line in enumerate(lines):
        t = i / max(n - 1, 1)
        art.append(line + "\n", style=_lerp(C1, C2, t))

    FIELDS = [
        ("Project",     "YTFS"),
        ("Description", "Store files inside videos"),
        ("Language",    "Python"),
        ("Encryption",  "Fernet AES-128"),
        ("Resolution",  "1920×1080"),
        ("Output",      "MP4"),
        ("Repository",  "github.com/diluteoxygen/ytfs"),
    ]

    info = Text()
    info.append("diluteoxygen/ytfs\n\n", style="bold bright_magenta")
    for key, val in FIELDS:
        info.append(f"{key:<12}", style="bold bright_green")
        info.append(f": {val}\n", style="white")

    grid = Table.grid(padding=(0, 4))
    grid.add_column(no_wrap=True)
    grid.add_column(no_wrap=False)
    grid.add_row(art, info)

    console.print()
    console.print(grid)
    console.print()

def get_cipher(password: str, salt: bytes) -> Fernet:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=480000)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(password.encode())))

def get_password(mode: str, confirm: bool = False) -> str:
    pwd = os.environ.get("YTFS_PASS") or os.environ.get("PACKER_PASS")
    if pwd:
        return pwd
    pwd = getpass.getpass(f"Enter password to {mode}: ")
    if confirm:
        pwd2 = getpass.getpass("Confirm password: ")
        if pwd != pwd2:
            console.print("[bold red]Error: Passwords don't match.[/bold red]")
            sys.exit(1)
    return pwd

def format_size(size: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"

@app.command()
def pack(
    input_path: str = typer.Argument(..., help="File or folder to pack"),
    password: str = typer.Option(None, "--password", "-p", help="Encryption password"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt")
):
    """Pack a file or folder into an encrypted video."""
    input_path = Path(input_path)
    if not input_path.exists():
        console.print(f"[bold red]Error: '{input_path}' not found.[/bold red]")
        raise typer.Exit(1)

    is_dir = input_path.is_dir()
    
    # Pre-processing (Compression if directory)
    temp_dir = None
    temp_zip = None
    if is_dir:
        console.print(f"[cyan]Directory detected. Zipping {input_path}...[/cyan]")
        temp_dir = tempfile.mkdtemp()
        temp_zip_base = os.path.join(temp_dir, "archive")
        temp_zip_created = shutil.make_archive(temp_zip_base, 'zip', input_path)
        temp_zip = temp_zip_created
        process_path = Path(temp_zip)
    else:
        process_path = input_path

    file_size = process_path.stat().st_size
    if file_size == 0:
        console.print("[bold red]Error: Input file is empty.[/bold red]")
        if temp_zip: os.remove(temp_zip)
        raise typer.Exit(1)

    # Estimate capacity
    # metadata size is small, we estimate rough frame count
    estimated_payload_size = file_size + 16 + 8 + 1024 # padding + magic
    frames = (estimated_payload_size + BYTES_PER_FRAME - 1) // BYTES_PER_FRAME
    vid_length_sec = frames / 10.0

    # Auto generate output
    out_dir = Path("Output") / "Packed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{input_path.name}.mp4"

    # UI Panel
    stats_table = Table(show_header=False, box=None)
    stats_table.add_row("Input:", str(input_path))
    stats_table.add_row("Size:", format_size(file_size))
    stats_table.add_row("Type:", "Folder (Zipped)" if is_dir else "File")
    stats_table.add_row("", "")
    stats_table.add_row("Output:", str(out_file))
    stats_table.add_row("Frames:", str(frames))
    stats_table.add_row("Video Length:", f"{vid_length_sec:.1f} sec")
    stats_table.add_row("Resolution:", "1920x1080")
    stats_table.add_row("FPS:", "10")

    console.print(Panel(stats_table, title="Capacity Calculator", border_style="cyan"))

    if not yes:
        if not questionary.confirm("Proceed with packing?").ask():
            if temp_zip: os.remove(temp_zip)
            if temp_dir: shutil.rmtree(temp_dir)
            raise typer.Exit(0)

    if not password:
        password = get_password("pack", confirm=True)

    metadata = {
        "original_filename": input_path.name,
        "original_size": file_size,
        "is_compressed_folder": is_dir,
        "timestamp": time.time()
    }
    meta_json = json.dumps(metadata).encode('utf-8')
    meta_len = len(meta_json)

    with console.status("[cyan]Reading and encrypting...", spinner="dots"):
        with open(process_path, 'rb') as f:
            raw_data = f.read()

        salt = os.urandom(16)
        ciphertext = get_cipher(password, salt).encrypt(raw_data)
        
        # Payload: MAGIC(4) + META_LEN(4) + META(x) + SALT(16) + CIPHER_LEN(8) + CIPHER(y)
        payload = bytearray(MAGIC_BYTES)
        payload += meta_len.to_bytes(4, 'big')
        payload += meta_json
        payload += salt
        payload += len(ciphertext).to_bytes(8, 'big')
        payload += ciphertext

        pad_len = BYTES_PER_FRAME - (len(payload) % BYTES_PER_FRAME)
        if pad_len != BYTES_PER_FRAME:
            payload += b'\x00' * pad_len

        bits = np.unpackbits(np.frombuffer(payload, dtype=np.uint8)).reshape(-1, H_BLOCKS, W_BLOCKS, 3)

    writer = imageio.get_writer(out_file, fps=10, macro_block_size=1)
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Encoding frames...", total=len(bits))
        for frame_bits in bits:
            writer.append_data((np.repeat(np.repeat(frame_bits, BLOCK_SIZE, axis=0), BLOCK_SIZE, axis=1) * 255).astype(np.uint8))
            progress.advance(task)
            
    writer.close()
    if temp_zip and os.path.exists(temp_zip):
        os.remove(temp_zip)
    if temp_dir and os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)

    console.print(f"\n[bold green]Success![/bold green] Packed into {out_file}")

def read_video_metadata(reader):
    try:
        frame = reader.get_data(0)
    except IndexError:
        raise ValueError("Video is empty.")

    bits = (np.asarray(frame)[BLOCK_SIZE//2::BLOCK_SIZE, BLOCK_SIZE//2::BLOCK_SIZE, :] > 127).astype(np.uint8).flatten()
    extracted_bytes = np.packbits(bits).tobytes()

    if extracted_bytes[:4] != MAGIC_BYTES:
        raise ValueError("Not a valid YTFS v1.0 video (Magic bytes missing).")

    meta_len = int.from_bytes(extracted_bytes[4:8], 'big')
    header_end = 8 + meta_len + 16 + 8
    
    frames_needed = (header_end + BYTES_PER_FRAME - 1) // BYTES_PER_FRAME
    
    bits_list = [bits]
    for i in range(1, frames_needed):
        f = reader.get_data(i)
        bits_list.append((np.asarray(f)[BLOCK_SIZE//2::BLOCK_SIZE, BLOCK_SIZE//2::BLOCK_SIZE, :] > 127).astype(np.uint8).flatten())
        
    if frames_needed > 1:
        extracted_bytes = np.packbits(np.concatenate(bits_list)).tobytes()
        
    meta_json = extracted_bytes[8:8+meta_len]
    try:
        metadata = json.loads(meta_json.decode('utf-8'))
    except Exception:
        raise ValueError("Failed to parse metadata.")

    salt_start = 8 + meta_len
    salt = extracted_bytes[salt_start : salt_start + 16]
    cipher_len = int.from_bytes(extracted_bytes[salt_start + 16 : salt_start + 24], 'big')
    
    return metadata, salt, cipher_len, header_end

@app.command()
def inspect(input_path: str = typer.Argument(..., help="YTFS video to inspect")):
    """Inspect a YTFS video's metadata without unpacking."""
    input_path = Path(input_path)
    if not input_path.exists():
        console.print(f"[bold red]Error: '{input_path}' not found.[/bold red]")
        raise typer.Exit(1)

    try:
        reader = imageio.get_reader(input_path)
        frames_count = reader.count_frames()
        metadata, salt, cipher_len, header_end = read_video_metadata(reader)
        reader.close()
    except Exception as e:
        console.print(f"[bold red]Error reading video:[/bold red] {e}")
        raise typer.Exit(1)

    table = Table(title="YTFS Video Inspect", show_header=False, box=None)
    table.add_row("File Type:", "YTFS Video")
    table.add_row("Resolution:", "1920x1080")
    table.add_row("Frames:", str(frames_count))
    table.add_row("", "")
    table.add_row("Original Name:", metadata.get('original_filename', 'Unknown'))
    table.add_row("Original Size:", format_size(metadata.get('original_size', 0)))
    table.add_row("Is Folder:", "Yes" if metadata.get('is_compressed_folder') else "No")
    table.add_row("Encrypted:", "Yes")
    table.add_row("Cipher Payload:", format_size(cipher_len))
    
    console.print(Panel(table, border_style="cyan"))

@app.command()
def unpack(
    input_path: str = typer.Argument(..., help="YTFS video to unpack"),
    password: str = typer.Option(None, "--password", "-p", help="Encryption password")
):
    """Unpack a YTFS encrypted video back to its original file/folder."""
    input_path = Path(input_path)
    if not input_path.exists():
        console.print(f"[bold red]Error: '{input_path}' not found.[/bold red]")
        raise typer.Exit(1)

    try:
        reader = imageio.get_reader(input_path)
        metadata, salt, cipher_len, header_end = read_video_metadata(reader)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)

    frames_count = reader.count_frames()

    if not password:
        password = get_password("unpack")

    bits = []
    frames_to_read = min(frames_count, (header_end + cipher_len + BYTES_PER_FRAME - 1) // BYTES_PER_FRAME)
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Decoding frames...", total=frames_to_read)
        reader = imageio.get_reader(input_path)
        for idx, frame in enumerate(reader):
            if idx >= frames_to_read:
                break
            bits.append((np.asarray(frame)[BLOCK_SIZE//2::BLOCK_SIZE, BLOCK_SIZE//2::BLOCK_SIZE, :] > 127).astype(np.uint8).flatten())
            progress.advance(task)
        reader.close()

    extracted_bytes = np.packbits(np.concatenate(bits)).tobytes()
    ciphertext = extracted_bytes[header_end : header_end + cipher_len]

    with console.status("[cyan]Decrypting...", spinner="dots"):
        try:
            raw_data = get_cipher(password, salt).decrypt(ciphertext)
        except InvalidToken:
            console.print("[bold red]Error: Incorrect password or corrupted video.[/bold red]")
            raise typer.Exit(1)

    out_dir = Path("Output") / "Unpacked"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    is_dir = metadata.get("is_compressed_folder", False)
    orig_name = metadata.get("original_filename", "unpacked_file")
    
    if is_dir:
        temp_zip = out_dir / f"{orig_name}.zip"
        with open(temp_zip, 'wb') as f:
            f.write(raw_data)
        
        final_out = out_dir / orig_name
        console.print(f"[cyan]Extracting directory to {final_out}...[/cyan]")
        shutil.unpack_archive(temp_zip, final_out)
        os.remove(temp_zip)
    else:
        final_out = out_dir / orig_name
        with open(final_out, 'wb') as f:
            f.write(raw_data)

    console.print(f"\n[bold green]Success![/bold green] Unpacked into {final_out}")

@app.command()
def verify(
    input_path: str = typer.Argument(..., help="YTFS video to verify"),
    password: str = typer.Option(None, "--password", "-p", help="Encryption password")
):
    """Verify the password and integrity of a YTFS video."""
    input_path = Path(input_path)
    if not input_path.exists():
        console.print(f"[bold red]Error: '{input_path}' not found.[/bold red]")
        raise typer.Exit(1)

    try:
        reader = imageio.get_reader(input_path)
        metadata, salt, cipher_len, header_end = read_video_metadata(reader)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)
        
    frames_count = reader.count_frames()

    if not password:
        password = get_password("verify")

    with console.status("[cyan]Decoding and verifying...", spinner="dots"):
        bits = []
        frames_to_read = min(frames_count, (header_end + cipher_len + BYTES_PER_FRAME - 1) // BYTES_PER_FRAME)
        reader = imageio.get_reader(input_path)
        for idx, frame in enumerate(reader):
            if idx >= frames_to_read:
                break
            bits.append((np.asarray(frame)[BLOCK_SIZE//2::BLOCK_SIZE, BLOCK_SIZE//2::BLOCK_SIZE, :] > 127).astype(np.uint8).flatten())
        reader.close()
        
        extracted_bytes = np.packbits(np.concatenate(bits)).tobytes()
        ciphertext = extracted_bytes[header_end : header_end + cipher_len]

        try:
            get_cipher(password, salt).decrypt(ciphertext)
            console.print("[bold green]Verification successful! Password and data are valid.[/bold green]")
        except InvalidToken:
            console.print("[bold red]Verification failed! Incorrect password or corrupted video.[/bold red]")
            raise typer.Exit(1)

@app.command()
def benchmark(
    input_path: str = typer.Argument(..., help="File to benchmark"),
):
    """Run a test encode/decode loop to benchmark speeds."""
    input_path = Path(input_path)
    if not input_path.exists() or input_path.is_dir():
        console.print(f"[bold red]Error: '{input_path}' not found or is a directory.[/bold red]")
        raise typer.Exit(1)
        
    file_size = input_path.stat().st_size
    size_str = format_size(file_size)
    console.print(f"[bold cyan]Benchmarking YTFS end-to-end on {input_path.name} ({size_str})...[/bold cyan]\n")
    
    temp_dir = tempfile.mkdtemp()
    temp_video = os.path.join(temp_dir, "benchmark_out.mp4")
    
    try:
        # Benchmark Pack
        pack_start = time.time()
        # Directly call the pack functionality without interactive prompts
        pack(str(input_path), password="benchmark_password", yes=True)
        # The output file is created inside Output/Packed by default. Let's move it to our temp_dir
        expected_output = Path("Output/Packed") / f"{input_path.name}.mp4"
        if expected_output.exists():
            shutil.move(str(expected_output), temp_video)
        pack_time = time.time() - pack_start
        pack_speed = (file_size / (1024 * 1024)) / pack_time if pack_time > 0 else 0
        
        # Benchmark Unpack
        unpack_start = time.time()
        unpack(temp_video, password="benchmark_password")
        unpack_time = time.time() - unpack_start
        unpack_speed = (file_size / (1024 * 1024)) / unpack_time if unpack_time > 0 else 0
        
        # Clean up the output directories created
        packed_cleanup = Path("Output/Packed") / f"{input_path.name}.mp4"
        if packed_cleanup.exists():
            os.remove(packed_cleanup)
        unpacked_cleanup = Path("Output/Unpacked") / input_path.name
        if unpacked_cleanup.exists():
            if unpacked_cleanup.is_dir():
                shutil.rmtree(unpacked_cleanup)
            else:
                os.remove(unpacked_cleanup)
                
        # Print results
        table = Table(title="Benchmark Results", box=None)
        table.add_column("Operation", style="cyan")
        table.add_column("Time (s)", style="magenta", justify="right")
        table.add_column("Speed (MB/s)", style="green", justify="right")
        table.add_row("Packing (Encoding)", f"{pack_time:.2f}s", f"{pack_speed:.2f} MB/s")
        table.add_row("Unpacking (Decoding)", f"{unpack_time:.2f}s", f"{unpack_speed:.2f} MB/s")
        
        console.print(Panel(table, border_style="green", title="Benchmark Complete"))
        
    except Exception as e:
        console.print(f"[bold red]Benchmark failed:[/bold red] {e}")
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """YTFS interactive CLI."""
    if ctx.invoked_subcommand is None:
        print_banner()
        custom_style = questionary.Style([
            ('qmark', 'fg:#BC84FF bold'),
            ('question', 'bold'),
            ('pointer', 'fg:#6430E0 bold'),
            ('highlighted', 'fg:#BC84FF bold'),
            ('selected', 'fg:#BC84FF'),
            ('separator', 'fg:#888888'),
        ])
        choice = questionary.select(
            "What would you like to do?",
            choices=[
                questionary.Choice("Pack     (Encode a file or folder into a video)", value="pack"),
                questionary.Choice("Unpack   (Extract original files from a video)", value="unpack"),
                questionary.Choice("Inspect  (Read unencrypted metadata from a video)", value="inspect"),
                questionary.Separator(),
                questionary.Choice("Exit", value="exit")
            ],
            style=custom_style
        ).ask()

        if choice == "pack":
            path = questionary.path("Path to file or folder:").ask()
            if path:
                try:
                    pack(input_path=path, password=None, yes=False)
                except typer.Exit:
                    pass
        elif choice == "unpack":
            path = questionary.path("Path to video:").ask()
            if path:
                try:
                    unpack(input_path=path, password=None)
                except typer.Exit:
                    pass
        elif choice == "inspect":
            path = questionary.path("Path to video:").ask()
            if path:
                try:
                    inspect(input_path=path)
                except typer.Exit:
                    pass
        else:
            console.print("[cyan]Goodbye![/cyan]")

if __name__ == "__main__":
    app()