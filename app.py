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
    # استخراج معرف الفيديو من أي رابط يوتيوب
    match = re.search(r"(?:v=|\/|youtu\.be\/)([0-9A-Za-z_-]{11})", url)
    return match.group(1) if match else None

def download_audio_from_piped(video_url, save_path):
    log_it(f"Trying to download via Piped API proxy for: {video_url}")
    video_id = extract_video_id(video_url)
    
    if not video_id:
        log_it("Could not extract Video ID from the URL.")
        return False
        
    log_it(f"Extracted Video ID: {video_id}")
    
    try:
        # استخدام شبكة Piped اللامركزية المفتوحة (لا تحتاج لمفاتيح أو تخطي حماية)
        api_url = f"https://pipedapi.kavin.rocks/streams/{video_id}"
        log_it(f"Connecting to Piped API: {api_url}")
        
        response = requests.get(api_url)
        log_it(f"Piped API Response Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            audio_streams = data.get("audioStreams", [])
            
            if audio_streams:
                log_it("Found audio streams! Selecting the best one...")
                stream_url = audio_streams[0].get("url")
                
                log_it("Downloading audio file...")
                audio_res = requests.get(stream_url)
                with open(save_path, 'wb') as f:
                    f.write(audio_res.content)
                log_it("Audio file downloaded and saved successfully!")
                return True
            else:
                log_it("No audio streams found in the Piped response.")
        else:
            log_it(f"Piped API Error: {response.text}")
    except Exception as e:
        log_it(f"Download Exception: {str(e)}")
        
    return False

def process_video_background(video_url, webhook_url, groq_key):
    log_it("Background processing thread started.")
    client = Groq(api_key=groq_key)
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = os.path.join(temp_dir, "audio_file")

            success = download_audio_from_piped(video_url, audio_path)
            
            if not success:
                log_it("Failed to get audio. Sending error message to n8n Webhook.")
                requests.post(webhook_url, json={"status": "error", "error_message": "فشل سحب الصوت من السيرفر الوسيط (Piped)."})
                return

            log_it("Starting audio chunking (cutting every 10 minutes)...")
            # استخدام from_file بدلاً من from_mp3 لتقبل أي صيغة صوتية تأتينا
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
