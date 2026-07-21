import os
import tempfile
import threading
import requests
from flask import Flask, request, jsonify
from groq import Groq
from pydub import AudioSegment

app = Flask(__name__)

def log_it(message):
    # هذه الدالة ستجبر السيرفر على كتابة ما يحدث في السجل فوراً
    print(f"[VEXIO LOG] {message}", flush=True)

def download_audio_from_api(video_url, save_path):
    log_it(f"Trying to download audio using Cobalt API for: {video_url}")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = {
        "url": video_url,
        "isAudioOnly": True,
        "aFormat": "mp3"
    }
    try:
        response = requests.post("https://api.cobalt.tools/api/json", json=payload, headers=headers)
        log_it(f"Cobalt API Status Code: {response.status_code}")
        
        if response.status_code == 200:
            audio_link = response.json().get("url")
            if audio_link:
                log_it("Audio link generated successfully! Downloading MP3 file now...")
                r = requests.get(audio_link)
                with open(save_path, 'wb') as f:
                    f.write(r.content)
                log_it("MP3 Downloaded successfully!")
                return True
        else:
            log_it(f"Cobalt API Error: {response.text}")
    except Exception as e:
        log_it(f"Download Exception: {str(e)}")
    return False

def process_video_background(video_url, webhook_url, groq_key):
    log_it("Background processing thread started.")
    client = Groq(api_key=groq_key)
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = os.path.join(temp_dir, "audio.mp3")

            success = download_audio_from_api(video_url, audio_path)
            
            if not success:
                log_it("Failed to get audio. Sending error message to n8n Webhook.")
                requests.post(webhook_url, json={"status": "error", "error_message": "فشل سحب الصوت من السيرفر الوسيط."})
                return

            log_it("Starting audio chunking (cutting every 10 minutes)...")
            audio = AudioSegment.from_mp3(audio_path)
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
            
            log_it("Transcription complete! Sending the final text to n8n Webhook...")
            requests.post(webhook_url, json={"status": "success", "text": full_text})
            log_it("Done successfully! Process finished.")

    except Exception as e:
        log_it(f"FATAL ERROR: {str(e)}")
        requests.post(webhook_url, json={"status": "error", "error_message": str(e)})

@app.route('/process', methods=['POST'])
def process_video():
    data = request.json
    url = data.get('url')
    webhook_url = data.get('webhook_url')
    groq_key = os.environ.get("GROQ_API_KEY")

    log_it(f"INCOMING REQUEST RECEIVED from n8n for URL: {url}")

    if not url or not webhook_url:
        log_it("Missing URL or Webhook in the request!")
        return jsonify({"error": "Missing URL or Webhook"}), 400

    thread = threading.Thread(target=process_video_background, args=(url, webhook_url, groq_key))
    thread.start()

    log_it("Instant success response sent back to n8n HTTP node.")
    return jsonify({"message": "تم استلام الطلب بنجاح. سيتم إرسال النص المفرغ فور الانتهاء."}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
