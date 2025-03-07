import os
import openai  # For OpenAI GPT-4O API
import ffmpeg
from telegram import Update, InputFile
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import tempfile
import uuid  # For unique filenames
import shutil  # For cleaning up temporary files
import logging
from collections import defaultdict
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("/home/ubuntu/KtuvitBot/bot.log"),  # Log to file
        logging.StreamHandler()  # Log to systemd/journalctl
    ]
)

# Set your API keys
TELEGRAM_BOT_TOKEN = os.getenv('KTUVIT_TELEGRAM_BOT_TOKEN')
openai.api_key = os.getenv('OPENAI_API_KEY')

# Default target language
default_language = 'Hebrew'

# Track video count per user and last reset time
user_video_count = defaultdict(int)
user_last_reset = defaultdict(lambda: datetime.now())

# Store user language preferences
user_languages = defaultdict(lambda: "Hebrew")

# Read allowed user IDs from a file
def load_allowed_users():
    try:
        with open('allowed_users.txt', 'r') as f:
            return [int(line.strip()) for line in f if line.strip().isdigit()]
    except FileNotFoundError:
        logging.error("allowed_users.txt not found. No users will be allowed.")
        return []

# Whitelist of allowed user IDs
WHITELISTED_USER_IDS = load_allowed_users()
logging.info(f"Loaded {len(WHITELISTED_USER_IDS)} allowed users.")

# Check if a user can upload a video
def can_upload_video(user_id):
    if user_id in WHITELISTED_USER_IDS:
        return True

    if datetime.now() - user_last_reset[user_id] > timedelta(days=1):
        user_video_count[user_id] = 0
        user_last_reset[user_id] = datetime.now()

    return user_video_count[user_id] < 5

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
    if user_id not in WHITELISTED_USER_IDS:
        if not can_upload_video(user_id):
            update.message.reply_text("You've reached the daily limit of 5 videos. Please try again tomorrow.")
            return

    update.message.reply_text(
        "Send me a video, and I'll generate subtitles for it. Default language is Hebrew. "
        "You can change the language by sending /setlanguage <language_name> (e.g., /setlanguage Spanish)."
    )

# Command to set the target language for subtitles
def set_language(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    logging.info(f"User {user_id} is trying to set language.")

    if not can_upload_video(user_id):
        update.message.reply_text("You've reached the daily limit. You cannot change the language right now.")
        return

    language_name = " ".join(context.args).strip().title()
    if language_name:
        user_languages[user_id] = language_name
        update.message.reply_text(f"Language set to {language_name}.")
        logging.info(f"User {user_id} set language to {language_name}.")
    else:
        update.message.reply_text("Please specify a language name. Example: /setlanguage Spanish")

# Translate the entire SRT content to the target language using OpenAI GPT-4O
def translate_srt(srt_content: str, target_language: str) -> str:
    logging.info(f"Translating entire SRT content to {target_language} using OpenAI GPT-4O...")

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

        fixed_lines = []
        for line in translated_content.splitlines():
            if line.strip() and not line.strip().isdigit() and '-->' not in line:
                line = f"{rtl_start}{line}{rtl_end}"
            fixed_lines.append(line)

        translated_content = "\n".join(fixed_lines)
        logging.info("RTL fix applied successfully.")

    return translated_content

# Function to handle video files sent by the user
def handle_video(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    if not can_upload_video(user_id):
        update.message.reply_text("You've reached the daily limit of 5 videos. Please try again tomorrow.")
        return

    user_video_count[user_id] += 1
    send_status(update, context, "Processing your video...")

    video_file = update.message.video or update.message.document
    if not video_file:
        update.message.reply_text("Please send a video file.")
        return

    original_filename = video_file.file_name or f"video_{uuid.uuid4().hex}.mp4"
    filename_base = os.path.splitext(original_filename)[0]

    with tempfile.TemporaryDirectory() as tmpdir:
        video_path = os.path.join(tmpdir, f"{uuid.uuid4().hex}_{original_filename}")
        output_video_path = os.path.join(tmpdir, f"{filename_base}_sub.mp4")
        translated_srt_path = os.path.join(tmpdir, f"{uuid.uuid4().hex}_subtitles_translated.srt")
        audio_path = os.path.join(tmpdir, f"{uuid.uuid4().hex}_audio.wav")

        send_status(update, context, "Downloading video...")
        video = context.bot.get_file(video_file.file_id)
        video.download(video_path)

        send_status(update, context, "Extracting audio and transcribing...")
        ffmpeg.input(video_path).output(audio_path).run(quiet=True)

        with open(audio_path, "rb") as audio_file:
            result = openai.Audio.transcribe(
                model="whisper-1",
                file=audio_file,
                response_format="srt"
            )

        target_language = user_languages[user_id]
        translated_srt_content = translate_srt(result, target_language)

        with open(translated_srt_path, 'w') as translated_file:
            translated_file.write(translated_srt_content)

        send_status(update, context, "Generating video with subtitles...")
        ffmpeg.input(video_path).output(output_video_path, vf=f"subtitles={translated_srt_path}").run(quiet=True)

        send_status(update, context, "Uploading your video with subtitles!")
        with open(output_video_path, 'rb') as video_file:
            context.bot.send_video(chat_id=update.message.chat_id, video=video_file, filename=f"{filename_base}_sub.mp4")

# Main function to start the bot
def main():
    updater = Updater(TELEGRAM_BOT_TOKEN)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("setlanguage", set_language))
    dp.add_handler(MessageHandler(Filters.video | Filters.document, handle_video))

    logging.info("Bot started.")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()

