# KtuvitBot
<p align="center">
  <img src="https://i.imgur.com/T8DNS5S.jpeg" alt="KtuvitBot Logo" width="200"/>
</p>

**KtuvitBot** is a Telegram bot that generates subtitles for videos in different languages using OpenAI's Whisper for transcription and GPT-5.1 for translation. The bot burns subtitles into the video and also delivers the SRT files directly.

## 🚀 Features

- 🎥 **Transcribes and translates video subtitles** — burns subtitles into video and sends SRT files
- 🤖 **Models**: `whisper-1` for transcription, `gpt-5.1` for translation
- 🔬 **Enhance mode** (`/enhance`) — runs `gpt-4o-transcribe` in parallel with Whisper and uses AI to merge the best of both for improved accuracy
- 🌍 **Supports multiple languages** via `/setlanguage <language>`
- 🌀 **Applies RTL fixes** for Hebrew subtitles
- 📊 **Daily usage limits**: 5/day free, 10/day (send `AmYisraelChai`), 50/day (`/shared <social-link>`)
- 🔑 **Unlimited access** for whitelisted users (`allowed_users.txt`)
- 📈 **Admin metrics** via `/metrics` (whitelisted users only) — usage stats for today, 7d, 30d
- 🔎 **Verbose mode** (`/verbose`) — also sends all SRT stages as text messages
- 📢 **Sends status updates** to users during processing

## 📦 Installation

### 1. Clone the repository
```bash
git clone https://github.com/shlomota/KtuvitBot.git
cd KtuvitBot
```

### 2. Create a virtual environment
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Install FFmpeg

**🐧 Ubuntu/Debian**
```bash
sudo apt-get update
sudo apt-get install ffmpeg
```

**🍏 MacOS (using Homebrew)**
```bash
brew install ffmpeg
```

**🖼️ Windows**
- Download FFmpeg from [FFmpeg.org](https://ffmpeg.org/download.html).
- Extract and add the bin folder to your system PATH.

### 5. Set environment variables
Create a Telegram bot using BotFather and save the provided token.

Set your API keys in the terminal:
```bash
export KTUVIT_TELEGRAM_BOT_TOKEN='your-telegram-bot-token'
export OPENAI_API_KEY='your-openai-api-key'
```

Or add them to .bashrc or .bash_profile for persistence:
```bash
echo "export KTUVIT_TELEGRAM_BOT_TOKEN='your-telegram-bot-token'" >> ~/.bashrc
echo "export OPENAI_API_KEY='your-openai-api-key'" >> ~/.bashrc
source ~/.bashrc
```

### 6. Create allowed_users.txt (optional)

Create a file named `allowed_users.txt` and add the Telegram user IDs of users who should have unlimited access:
```
123456789
987654321
```

### 7. Run the bot

Run the bot:
```bash
python main.py
```
