import os
import tempfile
import threading
import requests
from flask import Flask, request, jsonify
from groq import Groq
from pydub import AudioSegment
from pytubefix import YouTube

app = Flask(__name__)

def log_it(message):
    print(f"[VEXIO LOG] {message}", flush=True)

def download_audio_pytubefix(video_url, save_path):
    try:
        log_it(f"Downloading audio using pytubefix for: {video_url}")
        # استخدام إضافة pytubefix التي تتجاوز حماية يوتيوب تلقائياً
        yt = YouTube(video_url, use_po_token=True)
        audio_stream = yt.streams.get_audio_only()
        if audio_stream:
            audio_stream.download(filename=save_path)
            log_it("Download successful via pytubefix!")
            return True
    except Exception as e:
        log_it(f"Download Error: {str(e)}")
    return False

def process_video_background(video_url, webhook_url, groq_key):
    log_it("Background processing started.")
    client = Groq(api_key=groq_key)
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = os.path.join(temp_dir, "audio.mp3")

            # سحب الصوت بالأداة الجديدة
            success = download_audio_pytubefix(video_url, audio_path)
            
            if not success:
                requests.post(webhook_url, json={"status": "error", "error_message": "فشل التحميل بسبب حماية يوتيوب القصوى."})
                return

            log_it("Starting audio chunking...")
            audio = AudioSegment.from_file(audio_path)
            chunk_length_ms = 10 * 60 * 1000
            chunks = [audio[i:i+chunk_length_ms] for i in range(0, len(audio), chunk_length_ms)]
            log_it(f"Audio split into {len(chunks)} chunks.")

            full_text = ""
            for i, chunk in enumerate(chunks):
                log_it(f"Processing chunk {i+1} out of {len(chunks)} using Groq...")
                chunk_path = os.path.join(temp_dir, f"chunk_{i}.mp3")
                chunk.export(chunk_path, format="mp3", bitrate="64k")

                with open(chunk_path, "rb") as file:
                    transcription = client.audio.transcriptions.create(
                      file=(os.path.basename(chunk_path), file.read()),
                      model="whisper-large-v3",
                    )
                    full_text += transcription.text + " "
            
            log_it("Transcription complete! Sending to Webhook...")
            requests.post(webhook_url, json={"status": "success", "text": full_text})
            log_it("Process finished.")

    except Exception as e:
        log_it(f"FATAL ERROR: {str(e)}")
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

    return jsonify({"message": "تم استلام الطلب."}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
