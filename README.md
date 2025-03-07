# KtuvitBot

**KtuvitBot** is a Telegram bot that generates subtitles for videos in different languages using OpenAI's Whisper API for transcription and GPT-4O for translation. The bot also applies RTL fixes for Hebrew and supports daily usage limits for free users.

## 🚀 Features

- 🎥 **Transcribes and translates video subtitles** using Whisper and GPT-4O
- 🌍 **Supports multiple languages** with per-user settings
- 🌀 **Applies RTL fixes** for Hebrew subtitles to ensure proper punctuation display
- 🔄 **Limits free users to 5 videos per day** (no limit for whitelisted users)
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
