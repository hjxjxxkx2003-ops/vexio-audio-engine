import os
import tempfile
import threading
import requests
import re
from flask import Flask, request, jsonify
from groq import Groq
from pydub import AudioSegment

app = Flask(__name__)

def log_it(message):
    print(f"[VEXIO LOG] {message}", flush=True)

def extract_video_id(url):
    match = re.search(r"(?:v=|\/|youtu\.be\/)([0-9A-Za-z_-]{11})", url)
    return match.group(1) if match else None

def download_audio_from_piped(video_url, save_path):
    video_id = extract_video_id(video_url)
    if not video_id:
        return False

    # قائمة سيرفرات الطوارئ (إذا تعطل واحد، ينتقل للثاني تلقائياً)
    instances = [
        "https://pipedapi.tokhmi.xyz",
        "https://pipedapi.adminforge.de",
        "https://pipedapi.qdi.fi",
        "https://pipedapi.kavin.rocks"
    ]

    for instance in instances:
        try:
            log_it(f"Trying server: {instance}...")
            api_url = f"{instance}/streams/{video_id}"
            response = requests.get(api_url, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                audio_streams = data.get("audioStreams", [])
                if audio_streams:
                    stream_url = audio_streams[0].get("url")
                    log_it("Audio found! Downloading...")
                    audio_res = requests.get(stream_url)
                    with open(save_path, 'wb') as f:
                        f.write(audio_res.content)
                    log_it("Download successful!")
                    return True
        except:
            log_it(f"Server {instance} failed. Switching to next...")
            continue
            
    return False

def process_video_background(video_url, webhook_url, groq_key):
    log_it("Background processing started.")
    client = Groq(api_key=groq_key)
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = os.path.join(temp_dir, "audio_file")

            success = download_audio_from_piped(video_url, audio_path)
            
            if not success:
                requests.post(webhook_url, json={"status": "error", "error_message": "فشلت كل السيرفرات في سحب الصوت."})
                return

            audio = AudioSegment.from_file(audio_path)
            chunk_length_ms = 10 * 60 * 1000
            chunks = [audio[i:i+chunk_length_ms] for i in range(0, len(audio), chunk_length_ms)]

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
            
            requests.post(webhook_url, json={"status": "success", "text": full_text})
            log_it("Process finished and sent to n8n.")

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

    return jsonify({"message": "تم استلام الطلب."}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
