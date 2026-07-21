import os
import tempfile
import threading
import requests
from flask import Flask, request, jsonify
import yt_dlp
from groq import Groq
from pydub import AudioSegment

app = Flask(__name__)

def process_video_background(video_url, webhook_url, groq_key):
    client = Groq(api_key=groq_key)
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = os.path.join(temp_dir, "audio.mp3")

            # 1. سحب الصوت والتخفي كأننا هاتف أندرويد
            ydl_opts = {
                'format': 'worstaudio/worst',
                'outtmpl': audio_path,
                'extractor_args': {'youtube': ['client=android']},
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '64',
                }],
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])

            # 2. تقطيع الصوت (كل 10 دقائق)
            audio = AudioSegment.from_mp3(audio_path)
            chunk_length_ms = 10 * 60 * 1000
            chunks = [audio[i:i+chunk_length_ms] for i in range(0, len(audio), chunk_length_ms)]

            # 3. التفريغ عبر Groq
            full_text = ""
            for i, chunk in enumerate(chunks):
                chunk_path = os.path.join(temp_dir, f"chunk_{i}.mp3")
                chunk.export(chunk_path, format="mp3", bitrate="64k")

                with open(chunk_path, "rb") as file:
                    transcription = client.audio.transcriptions.create(
                      file=(os.path.basename(chunk_path), file.read()),
                      model="whisper-large-v3",
                    )
                    full_text += transcription.text + " "

            # 4. الإرسال إلى n8n
            requests.post(webhook_url, json={"status": "success", "text": full_text})

    except Exception as e:
        requests.post(webhook_url, json={"status": "error", "error_message": str(e)})

@app.route('/process', methods=['POST'])
def process_video():
    data = request.json
    url = data.get('url')
    webhook_url = data.get('webhook_url')
    groq_key = os.environ.get("GROQ_API_KEY")

    if not url or not webhook_url:
        return jsonify({"error": "Missing URL or Webhook"}), 400

    thread = threading.Thread(target=process_video_background, args=(url, webhook_url, groq_key))
    thread.start()

    return jsonify({"message": "تم استلام الطلب بنجاح. سيتم إرسال النص المفرغ فور الانتهاء."}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
