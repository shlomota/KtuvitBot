import os
import json
import csv
import re
import threading
import openai  # OpenAI GPT-4O API
import ffmpeg
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import tempfile
import uuid
import shutil
import logging
from collections import defaultdict
from datetime import datetime, timedelta, date

# Configure logging
logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("/home/ubuntu/KtuvitBot/bot.log"),  # Log to file
            logging.StreamHandler()  # Log to systemd/journalctl
        ]
)

# Set API keys
TELEGRAM_BOT_TOKEN = os.getenv('KTUVIT_TELEGRAM_BOT_TOKEN')
openai.api_key = os.getenv('OPENAI_API_KEY')

# Default target language
default_language = 'Hebrew'

# Track video/audio count per user and last reset time
user_video_count = defaultdict(int)
user_last_reset = defaultdict(lambda: datetime.now())

# Store user language preferences
user_languages = defaultdict(lambda: "Hebrew")

# Users with verbose mode enabled (also send SRT as text)
user_verbose = set()

# Locks
tier_lock = threading.Lock()
metrics_lock = threading.Lock()

# File paths
TIER_USERS_FILE = '/home/ubuntu/KtuvitBot/tier_users.csv'
SHARES_FILE = '/home/ubuntu/KtuvitBot/shares.csv'
METRICS_FILE = '/home/ubuntu/KtuvitBot/metrics.json'

# Supported social media domains for /shared
SOCIAL_DOMAINS = {'facebook.com', 'x.com', 'twitter.com', 'linkedin.com'}

# Read allowed user IDs from a file
def load_allowed_users():
        try:
            with open('allowed_users.txt', 'r') as f:
                return [int(line.strip()) for line in f if line.strip().isdigit()]
        except FileNotFoundError:
            logging.error("allowed_users.txt not found. No users will be allowed.")
            return []

# Load tier users from CSV: {user_id: tier_limit}
def load_tier_users():
        result = {}
        try:
            with open(TIER_USERS_FILE, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    result[int(row['user_id'])] = int(row['tier'])
        except FileNotFoundError:
            pass
        except Exception as e:
            logging.error(f"Error loading tier_users.csv: {e}")
        return result

# Save tier users to CSV (call with tier_lock held)
def save_tier_users():
        with open(TIER_USERS_FILE, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['user_id', 'tier'])
            writer.writeheader()
            for uid, tier in tier_users.items():
                writer.writerow({'user_id': uid, 'tier': tier})

# Whitelist of allowed user IDs (unlimited access)
WHITELISTED_USER_IDS = load_allowed_users()
logging.info(f"Loaded {len(WHITELISTED_USER_IDS)} allowed users.")

# Tiered users: user_id → daily limit (10 or 50)
tier_users = load_tier_users()
logging.info(f"Loaded {len(tier_users)} tiered users.")

# --- Metrics ---

def record_metric(user_id, msg_type):
        """Record a user interaction. msg_type: 'cmd' or 'vid'"""
        today = date.today().isoformat()
        with metrics_lock:
            metrics = {}
            try:
                with open(METRICS_FILE, 'r') as f:
                    metrics = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                pass

            if today not in metrics:
                metrics[today] = {'users': [], 'cmd_messages': 0, 'vid_messages': 0}

            uid_str = str(user_id)
            if uid_str not in metrics[today]['users']:
                metrics[today]['users'].append(uid_str)

            if msg_type == 'cmd':
                metrics[today]['cmd_messages'] += 1
            elif msg_type == 'vid':
                metrics[today]['vid_messages'] += 1

            with open(METRICS_FILE, 'w') as f:
                json.dump(metrics, f)

def get_metrics_for_range(metrics, days):
        """Aggregate metrics over the last `days` days (inclusive of today)."""
        cutoff = date.today() - timedelta(days=days - 1)
        users = set()
        cmd_msgs = 0
        vid_msgs = 0
        for date_str, data in metrics.items():
            try:
                d = date.fromisoformat(date_str)
            except ValueError:
                continue
            if d >= cutoff:
                users.update(data.get('users', []))
                cmd_msgs += data.get('cmd_messages', 0)
                vid_msgs += data.get('vid_messages', 0)
        return len(users), cmd_msgs, vid_msgs

def metrics_command(update: Update, context: CallbackContext):
        user_id = update.message.from_user.id
        if user_id not in WHITELISTED_USER_IDS:
            update.message.reply_text("Unauthorized.")
            return

        with metrics_lock:
            try:
                with open(METRICS_FILE, 'r') as f:
                    metrics = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                metrics = {}

        u1, c1, v1 = get_metrics_for_range(metrics, 1)
        u7, c7, v7 = get_metrics_for_range(metrics, 7)
        u30, c30, v30 = get_metrics_for_range(metrics, 30)

        msg = (
            "Bot Metrics\n\n"
            f"Today:     {u1} users | {c1} commands | {v1} videos\n"
            f"Last 7d:   {u7} users | {c7} commands | {v7} videos\n"
            f"Last 30d:  {u30} users | {c30} commands | {v30} videos"
        )
        update.message.reply_text(msg)

# --- Tier upgrades ---

def upgrade_tier10(update: Update, context: CallbackContext):
        user_id = update.message.from_user.id
        with tier_lock:
            if user_id in WHITELISTED_USER_IDS:
                update.message.reply_text("You already have unlimited access!")
                return
            current = tier_users.get(user_id, 5)
            if current >= 50:
                update.message.reply_text("You're already on the 50/day plan!")
                return
            if current >= 10:
                update.message.reply_text(
                    "You're already on the 10/day plan. "
                    "Share this bot on social media and send /shared <link> to upgrade to 50/day."
                )
                return
            tier_users[user_id] = 10
            save_tier_users()
        logging.info(f"User {user_id} upgraded to tier 10.")
        update.message.reply_text("Am Yisrael Chai! You've been upgraded to 10 requests per day.")

def shared_command(update: Update, context: CallbackContext):
        user_id = update.message.from_user.id

        if not context.args:
            update.message.reply_text(
                "Usage: /shared <link>\n"
                "Share a post about this bot on Facebook, X (Twitter), or LinkedIn and send the link here."
            )
            return

        url = context.args[0].strip()

        # Validate URL domain
        match = re.match(r'https?://(?:www\.)?([^/]+)', url)
        if not match or match.group(1) not in SOCIAL_DOMAINS:
            update.message.reply_text(
                "Invalid link. Please share a post from Facebook, X (Twitter), or LinkedIn and send the link."
            )
            return

        with tier_lock:
            if user_id in WHITELISTED_USER_IDS:
                update.message.reply_text("You already have unlimited access!")
                return
            current = tier_users.get(user_id, 5)
            if current >= 50:
                update.message.reply_text("You're already on the 50/day plan!")
                return

            # Log the share to CSV
            timestamp = datetime.now().isoformat()
            try:
                file_exists = os.path.exists(SHARES_FILE)
                with open(SHARES_FILE, 'a', newline='') as f:
                    writer = csv.writer(f)
                    if not file_exists:
                        writer.writerow(['user_id', 'share_url', 'timestamp'])
                    writer.writerow([user_id, url, timestamp])
            except Exception as e:
                logging.error(f"Error saving share: {e}")

            tier_users[user_id] = 50
            save_tier_users()

        logging.info(f"User {user_id} upgraded to tier 50 via share: {url}")
        update.message.reply_text("Thank you for sharing! You've been upgraded to 50 requests per day.")

# --- Rate limiting ---

def daily_limit_for(user_id):
        if user_id in WHITELISTED_USER_IDS:
            return "unlimited"
        return tier_users.get(user_id, 5)

# Check if a user can upload a video/audio
def can_upload_media(user_id):
        if user_id in WHITELISTED_USER_IDS:
            return True

        if datetime.now() - user_last_reset[user_id] > timedelta(days=1):
            user_video_count[user_id] = 0
            user_last_reset[user_id] = datetime.now()

        limit = tier_users.get(user_id, 5)
        return user_video_count[user_id] < limit

# --- Bot commands ---

# Send status messages to the user
def send_status(update, context, message):
        try:
            context.bot.send_message(chat_id=update.message.chat_id, text=message)
        except Exception as e:
            logging.error(f"Failed to send message: {e}")

# Command to start the bot
def start(update: Update, context: CallbackContext):
        user_id = update.message.from_user.id
        logging.info(f"User {user_id} sent /start.")
        limit = daily_limit_for(user_id)
        update.message.reply_text(
            "Send me a video or an audio file (MP3/WAV). I will transcribe it and translate subtitles.\n\n"
            "Default language is Hebrew. Use /setlanguage <language> to change the subtitle language.\n\n"
            f"Your daily limit: {limit} requests.\n"
            "Send AmYisraelChai to unlock 10/day.\n"
            "Share this bot on social media and send /shared <link> to unlock 50/day.\n\n"
            "Use /verbose to also receive subtitles as text."
        )
        record_metric(user_id, 'cmd')

# Command to toggle verbose mode (also sends SRT content as text)
def verbose_command(update: Update, context: CallbackContext):
        user_id = update.message.from_user.id
        if user_id in user_verbose:
            user_verbose.discard(user_id)
            update.message.reply_text("Verbose mode OFF.")
        else:
            user_verbose.add(user_id)
            update.message.reply_text("Verbose mode ON. I will also send the translated SRT as text.")
        logging.info(f"User {user_id} toggled verbose mode: {'ON' if user_id in user_verbose else 'OFF'}")

# Command to set the target language
def set_language(update: Update, context: CallbackContext):
        user_id = update.message.from_user.id
        logging.info(f"User {user_id} is trying to set language.")

        if not can_upload_media(user_id):
            update.message.reply_text("You've reached the daily limit. You cannot change the language right now.")
            return

        language_name = " ".join(context.args).strip().title()
        if language_name:
            user_languages[user_id] = language_name
            update.message.reply_text(f"Language set to {language_name}.")
            logging.info(f"User {user_id} set language to {language_name}.")
        else:
            update.message.reply_text("Please specify a language name. Example: /setlanguage Spanish")
        record_metric(user_id, 'cmd')

# Translate SRT to target language using GPT-4O
def translate_srt(srt_content: str, target_language: str) -> str:
        logging.info(f"Translating SRT to {target_language} using GPT-4O...")

        is_rtl = target_language.lower() == "hebrew"

        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a professional translator."},
                {"role": "user", "content": (
                    f"Translate the following SRT subtitles to {target_language} while preserving the exact SRT format. "
                    "Return only the translated SRT content between <start> and <end> tags, without any additional explanations or text. "
                    "Do not modify the timestamps or numbers in the SRT file.\n\n"
                    f"{srt_content}"
                )}
            ],
            max_tokens=3000
        )

        translated_content = response['choices'][0]['message']['content'].strip()

        if '<start>' in translated_content and '<end>' in translated_content:
            translated_content = translated_content.split('<start>')[1].split('<end>')[0].strip()

        if is_rtl:
            logging.info("Applying RTL fix for Hebrew subtitles...")
            rtl_start = '\u202B'
            rtl_end = '\u202C'
            translated_content = "\n".join([
                f"{rtl_start}{line}{rtl_end}" if line and '-->' not in line and not line.isdigit() else line
                for line in translated_content.splitlines()
            ])
            logging.info("RTL fix applied successfully.")

        return translated_content

# Handle video and audio files
def handle_media(update: Update, context: CallbackContext):
        user_id = update.message.from_user.id
        limit = daily_limit_for(user_id)
        if not can_upload_media(user_id):
            update.message.reply_text(
                f"You've reached your daily limit of {limit} uploads. Please try again tomorrow.\n"
                "Send AmYisraelChai to unlock 10/day, or /shared <link> to unlock 50/day."
            )
            return

        user_video_count[user_id] += 1
        record_metric(user_id, 'vid')
        send_status(update, context, "Processing your file...")

        media_file = update.message.video or update.message.document or update.message.audio
        if not media_file:
            update.message.reply_text("Please send a video or audio file (MP3/WAV).")
            return

        original_filename = media_file.file_name or f"file_{uuid.uuid4().hex}"
        filename_base, file_extension = os.path.splitext(original_filename)
        is_audio = file_extension.lower() in [".mp3", ".wav"]

        with tempfile.TemporaryDirectory() as tmpdir:
            media_path = os.path.join(tmpdir, original_filename)
            output_video_path = os.path.join(tmpdir, f"{filename_base}_sub.mp4")
            translated_srt_path = os.path.join(tmpdir, f"{filename_base}_translated.srt")

            if media_file.file_size and media_file.file_size > 20 * 1024 * 1024:
                update.message.reply_text(
                    "File is too large (over 20MB). Please compress it and try uploading again."
                )
                return

            send_status(update, context, "Downloading file...")
            media = context.bot.get_file(media_file.file_id)
            media.download(media_path)

            # Extract audio if it's a video file
            audio_path = media_path
            if not is_audio:
                send_status(update, context, "Extracting audio from video...")
                audio_path = os.path.join(tmpdir, f"{filename_base}_audio.mp3")
                ffmpeg.input(media_path).output(audio_path, acodec='libmp3lame', ab='128k').run(quiet=True)

            send_status(update, context, "Transcribing audio...")
            with open(audio_path, "rb") as audio_file:
                result = openai.Audio.transcribe(
                    model="whisper-1",
                    file=audio_file,
                    response_format="srt"
                )

            original_srt_path = os.path.join(tmpdir, f"{filename_base}_original.srt")

            # Save original SRT
            with open(original_srt_path, 'w') as srt_file:
                srt_file.write(result)

            # Send original SRT
            send_status(update, context, "Uploading original SRT file...")
            with open(original_srt_path, 'rb') as srt_file:
                context.bot.send_document(chat_id=update.message.chat_id, document=srt_file, filename=f"{filename_base}_original.srt")

            # Get user's target language
            target_language = user_languages[user_id]

            # Translate SRT
            send_status(update, context, f"Translating to {target_language}...")
            translated_srt = translate_srt(result, target_language)

            # Save translated SRT
            with open(translated_srt_path, 'w') as srt_file:
                srt_file.write(translated_srt)

            # Send translated SRT
            send_status(update, context, "Uploading translated SRT file...")
            with open(translated_srt_path, 'rb') as srt_file:
                context.bot.send_document(chat_id=update.message.chat_id, document=srt_file, filename=f"{filename_base}_translated_{target_language}.srt")

            if user_id in user_verbose:
                context.bot.send_message(chat_id=update.message.chat_id, text=result)
                context.bot.send_message(chat_id=update.message.chat_id, text=translated_srt)

            if not is_audio:
                send_status(update, context, "Embedding translated subtitles into video...")
                ffmpeg.input(media_path).output(
                    output_video_path,
                    vf="subtitles={}:force_style='FontSize=16,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,MarginV=20,Alignment=2'".format(translated_srt_path)
                ).run(quiet=True)

                send_status(update, context, f"Uploading video with {target_language} subtitles!")
                with open(output_video_path, 'rb') as video_file:
                    context.bot.send_video(chat_id=update.message.chat_id, video=video_file, filename=f"{filename_base}_{target_language}_sub.mp4")

            shutil.rmtree(tmpdir)

# Start bot
def main():
        updater = Updater(TELEGRAM_BOT_TOKEN)
        dp = updater.dispatcher
        dp.add_handler(CommandHandler("start", start))
        dp.add_handler(CommandHandler("setlanguage", set_language))
        dp.add_handler(CommandHandler("verbose", verbose_command))
        dp.add_handler(CommandHandler("metrics", metrics_command))
        dp.add_handler(CommandHandler("shared", shared_command))
        dp.add_handler(MessageHandler(Filters.text & Filters.regex(r'^AmYisraelChai$'), upgrade_tier10))
        dp.add_handler(MessageHandler(Filters.video | Filters.document | Filters.audio, handle_media))
        logging.info("Bot started.")
        updater.start_polling()
        updater.idle()

if __name__ == "__main__":
        main()
