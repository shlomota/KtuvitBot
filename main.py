import os
import openai  # OpenAI GPT-4O API
import ffmpeg
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import tempfile
import uuid
import shutil
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

# Read allowed user IDs from a file
def load_allowed_users():
        try:
            with open('allowed_users.txt', 'r') as f:
                return [int(line.strip()) for line in f if line.strip().isdigit()]
        except FileNotFoundError:
            logging.error("allowed_users.txt not found. No users will be allowed.")
            return []

# Whitelist of allowed user IDs (unlimited access)
WHITELISTED_USER_IDS = load_allowed_users()
logging.info(f"Loaded {len(WHITELISTED_USER_IDS)} allowed users.")

# Check if a user can upload a video/audio
def can_upload_media(user_id):
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
        if user_id not in WHITELISTED_USER_IDS and not can_upload_media(user_id):
            update.message.reply_text("You've reached the daily limit of 5 uploads. Please try again tomorrow.")
            return

        update.message.reply_text(
            "Send me a **video or an audio file** (MP3/WAV). I will transcribe it and translate subtitles.\n\n"
            "Default language is Hebrew. Use `/setlanguage <language>` to change the subtitle language."
        )

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
        if not can_upload_media(user_id):
            update.message.reply_text("You've reached the daily limit of 5 uploads. Please try again tomorrow.")
            return

        user_video_count[user_id] += 1
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

            if not is_audio:
                send_status(update, context, "Embedding translated subtitles into video...")
                #ffmpeg.input(media_path).output(output_video_path, vf=f"subtitles={translated_srt_path}").run(quiet=True)

                ffmpeg.input(media_path).output(
                    output_video_path,
                    vf="subtitles={}:force_style='FontSize=28,PrimaryColour=&H0000FFFF,OutlineColour=&H80000000,BorderStyle=3,Outline=1,Shadow=0,MarginV=20'".format(translated_srt_path)
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
        dp.add_handler(MessageHandler(Filters.video | Filters.document | Filters.audio, handle_media))
        logging.info("Bot started.")
        updater.start_polling()
        updater.idle()

if __name__ == "__main__":
        main()
