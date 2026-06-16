
<p align="center">
  <img src="ytfs.png" width="110" alt="ytfs">
</p>

<h1 align="center">Youtube File System</h1>

You know the drill. Paying monthly for an S3 bucket or Google Drive to hold cold-storage archives you look at once a decade. The cloud is just someone else's computer. YouTube is also someone else's computer, but they let you upload 1080p videos for free.

`ytfs` securely packs your files into colored static, allowing you to use video hosting platforms as an infinite, free hard drive.

## Before / after

You want to back up a 50MB archive. The industry standard: configure Terraform, set up an AWS S3 bucket, provision IAM user roles, install the AWS CLI, write a sync script, and attach a credit card.

With `ytfs`:

```bash
# just pack it and upload it.
python packer.py pack archive.zip vacation.mp4
```

## The Upgrades

Early "YouTube File System" scripts mapped one bit of data to one 1x1 pixel. YouTube's VP9/AV1 compression algorithms immediately crushed those pixels into grey mush, destroying the file forever.

`ytfs` is built to survive in the wild:

* **8x8 Macro-Blocks:** Data is grouped into 8x8 pixel blocks. Even if YouTube blurs the edges, the center of the block remains perfectly readable.
* **Binary RGB:** Instead of black and white (1 bit), we use pure Red, Green, and Blue channels, securely packing 3 bits per macro-block.
* **Built-in AES-128:** Your data is encrypted *before* it becomes a video using PBKDF2 (480,000 iterations) + AES. If a bit flips, you'll know. If someone downloads your video, they just see noise.

## How it works

Before writing pixels, the engine stops at the core requirements:

```text
1. Generate random 16-byte salt.
2. Prompt for password -> derive AES key.
3. Encrypt file -> calculate exact padding.
4. Pack bytes -> 8x8 RGB chunks.
5. Spit out MP4.
```

When downloading, it reverses the process, reads the embedded salt, asks for your password, and drops your original `.zip` right back on your drive.

## Install

The most effort `ytfs` will ever ask of you. You need `ffmpeg` installed on your OS.

```bash
git clone https://github.com/diluteoxygen/ytfs.git
cd ytfs
pip install -r requirements.txt
```

## Commands

| Command | What it does |
| --- | --- |
| `pack <file> [out.mp4]` | Encrypts your file and generates the video payload. |
| `unpack <video.mp4> [out.zip]` | Scans the video, prompts for your password, and decrypts the original file. |

*Note: To download your video back from YouTube without the platform handing you a corrupted mobile format, use `yt-dlp`:*

```bash
yt-dlp -f "bestvideo[height=1080][ext=mp4]" <URL>
```

## FAQ

### Will YouTube ban me for doing this?

If they figure it out, maybe. But your payload is AES-encrypted. To Google's content ID algorithms, it just looks like 10 minutes of colorful TV static. Don't upload terabytes a day and you'll be fine.

### Why is there no React web frontend?

Because you don't need one. A web app requires bypassing CORS restrictions, decoding video frames in JavaScript, and melting your phone's battery. A CLI works today, tomorrow, and in ten years.

### Can I store my password in a config file?

No. Type it in.

### What if I forget my password?

Then you have a very colorful, very useless MP4 file. Write it down.

## License

[MIT](https://www.google.com/search?q=MIT+LICENSE)