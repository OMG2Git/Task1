from flask import Flask, request, jsonify
from flask_cors import CORS
import yt_dlp
from faster_whisper import WhisperModel
import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import time
import gspread
from google.oauth2.service_account import Credentials
import json
import re

app = Flask(__name__)
CORS(app)

# ========== CONFIGURATION ==========
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "Instagram Scripts")

# Load Whisper model once at startup
print("🔄 Loading Faster-Whisper model...")
WHISPER_MODEL = WhisperModel("base", device="cpu", compute_type="int8")
print("✅ Whisper model loaded")

NEWS_SOURCES = {
    "Lokmat Maharashtra": "https://www.lokmat.com/maharashtra/",
    "TV9 Marathi": "https://www.tv9marathi.com/",
    "ABP Majha": "https://marathi.abplive.com/"
}

def extract_video_id(url):
    """Extract video ID from YouTube URL"""
    match = re.search(r'(?:v=|\/)([a-zA-Z0-9_-]{11})', url)
    return match.group(1) if match else None

def download_video_audio(video_id):
    """Download only audio from YouTube video temporarily"""
    youtube_url = f"https://www.youtube.com/watch?v={video_id}"
    output_path = f'/tmp/{video_id}'
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_path + '.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '64',
        }],
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 30,
    }
    
    try:
        print(f"   ⬇️ Downloading audio for {video_id}...")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])
        
        audio_file = output_path + '.mp3'
        file_size = os.path.getsize(audio_file) / 1024 / 1024
        print(f"   ✅ Downloaded: {file_size:.1f} MB")
        return audio_file
        
    except Exception as e:
        print(f"   ❌ Download failed: {str(e)}")
        return None

def transcribe_with_whisper(audio_file):
    """Transcribe using faster-whisper"""
    try:
        print(f"   🎙️ Transcribing with Faster-Whisper...")
        
        segments, info = WHISPER_MODEL.transcribe(
            audio_file,
            language='hi',
            beam_size=5
        )
        
        transcript = ' '.join([segment.text for segment in segments])
        
        if os.path.exists(audio_file):
            os.remove(audio_file)
            print(f"   🗑️ Deleted temp file")
        
        transcript = transcript.strip()
        print(f"   ✅ Transcribed: {len(transcript)} chars")
        
        return transcript, 'hi'
        
    except Exception as e:
        print(f"   ❌ Transcription failed: {str(e)}")
        if os.path.exists(audio_file):
            os.remove(audio_file)
        return None, None

def call_perplexity_api(prompt, max_tokens=2500):
    """Call Perplexity Sonar API"""
    try:
        url = "https://api.perplexity.ai/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "sonar-pro",
            "messages": [
                {
                    "role": "system",
                    "content": "You are an expert Hindi news content creator specializing in viral Instagram Reels scripts."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": max_tokens,
            "temperature": 0.7,
            "top_p": 0.9,
            "return_citations": False,
            "stream": False
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        
        return response.json()['choices'][0]['message']['content']
        
    except Exception as e:
        print(f"   ⚠️ Perplexity API error: {str(e)}")
        raise e

def create_ai_summary(transcript, video_id):
    """Create AI summary using Perplexity Sonar API"""
    try:
        truncated = transcript[:12000] if len(transcript) > 12000 else transcript
        
        prompt = f"""You are a Hindi news summarizer. Extract 8-10 key news stories from this video transcript.

VIDEO ID: {video_id}

TRANSCRIPT:
{truncated}

TASK: Extract ALL important news stories with MAXIMUM details

For each story:
- Write 3-4 sentences in Hindi/Hinglish
- Include: what happened, who is involved, key facts (dates, numbers, places, quotes)
- Add background context if relevant
- Focus on concrete news (politics, accidents, court cases, schemes, protests, etc.)

FORMAT:
[1] Story headline - Detailed explanation in 3-4 sentences with all facts
[2] Next story - Detailed explanation with numbers, names, places
[3] Continue...

Write 8-10 stories. Keep total summary under 1500 words. Write in simple Hindi/Hinglish."""

        summary = call_perplexity_api(prompt, max_tokens=2500)
        print(f"   ✅ AI summary created: {len(summary)} characters")
        return summary
        
    except Exception as e:
        print(f"   ⚠️ Summary failed: {str(e)}")
        sentences = [s.strip() for s in transcript.replace('!', '.').replace('?', '.').split('.') if len(s.strip()) > 30]
        return '\n'.join(sentences[:15])

def scrape_news_headlines(url, source_name):
    """Scrape headlines from news websites"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        headlines = []
        
        for selector in ['h1', 'h2', 'h3', '.title', '.headline', 'a']:
            elements = soup.find_all(selector, limit=50)
            for elem in elements:
                text = elem.get_text(strip=True)
                if 20 < len(text) < 200:
                    headlines.append(text)
        
        unique_headlines = list(set(headlines))[:30]
        return unique_headlines
        
    except Exception as e:
        print(f"   ⚠️ Scraping {source_name} failed: {str(e)}")
        return []

def verify_news(all_summaries, scraped_news):
    """Verify news credibility using Perplexity Sonar API"""
    try:
        video_text = "\n\n".join([f"VIDEO {i+1}:\n{s[:800]}" for i, s in enumerate(all_summaries)])
        news_text = '\n'.join(scraped_news[:30])
        
        prompt = f"""You are a professional news fact-checker. Compare these video summaries with current headlines and provide a credibility score.

VIDEO SUMMARIES:
{video_text[:4000]}

CURRENT NEWS HEADLINES:
{news_text[:2000]}

TASK:
1. Identify which stories from videos are VERIFIED by the headlines
2. Identify which stories are UNVERIFIED (not found in headlines)
3. Calculate overall CREDIBILITY score (0-100%)

FORMAT:
✅ VERIFIED STORIES:
- [List verified stories]

⚠️ UNVERIFIED STORIES:
- [List unverified stories]

📊 CREDIBILITY SCORE: X%

EXPLANATION: [Brief explanation of the score]"""

        result = call_perplexity_api(prompt, max_tokens=1500)
        print(f"   ✅ Verification completed")
        return result
        
    except Exception as e:
        print(f"   ⚠️ Verification failed: {str(e)}")
        return "Verification unavailable"

def create_instagram_scripts(all_summaries, num_scripts, verification):
    """Generate viral Instagram scripts using Perplexity Sonar API"""
    try:
        combined = "\n\n".join([f"VIDEO {i+1}:\n{s[:800]}" for i, s in enumerate(all_summaries)])
        
        prompt = f"""You are India's #1 VIRAL Instagram Reels scriptwriter specializing in Hindi news content.

Create {num_scripts} SUPER ENGAGING, SUPER LONG Instagram Reels scripts in HINGLISH (55% Hindi + 45% English).

NEWS SUMMARIES:
{combined[:5000]}

VERIFICATION:
{verification[:600]}

⚠️ CRITICAL REQUIREMENTS FOR EACH SCRIPT:
1. LENGTH: 450-550 WORDS minimum (this is MANDATORY!)
2. STORIES: Cover 7-9 DIFFERENT news stories with FULL details
3. LANGUAGE: Natural Hinglish (mix Hindi and English fluently)
4. TONE: Energetic, conversational influencer style
5. STRUCTURE: 
   - Strong hook (10-15 seconds)
   - Story 1 with full details (30-40 seconds)
   - Story 2 with full details (30-40 seconds)
   - Continue for 7-9 stories
   - Powerful ending with CTA

6. INCLUDE: Names, numbers, dates, places, quotes
7. STYLE: Fast-paced, engaging, viral-worthy

FORMAT FOR EACH SCRIPT:
═══════════════════════
SCRIPT [NUMBER]
═══════════════════════
TITLE: [Catchy title in Hinglish]
THEME: [Theme category]
WORD COUNT: [Actual word count]

[FULL SCRIPT CONTENT - 500+ WORDS]
═══════════════════════

Generate ALL {num_scripts} scripts NOW. Each must be DIFFERENT and UNIQUE."""

        result = call_perplexity_api(prompt, max_tokens=8000)
        print(f"   ✅ Scripts generated: {len(result)} characters")
        return result
        
    except Exception as e:
        print(f"   ⚠️ Script generation failed: {str(e)}")
        return f"Error: {str(e)}"

def parse_scripts(raw_text, num_scripts):
    """Parse generated scripts"""
    scripts = []
    pattern = r'SCRIPT\s+(\d+)'
    parts = re.split(pattern, raw_text, flags=re.IGNORECASE)
    
    for i in range(1, len(parts), 2):
        if i+1 < len(parts):
            script_num = parts[i]
            content = parts[i+1].strip()
            
            title_match = re.search(r'TITLE:\s*(.+?)(?:\n|THEME:)', content, re.IGNORECASE)
            theme_match = re.search(r'THEME:\s*(.+?)(?:\n|WORD|═)', content, re.IGNORECASE)
            
            title = title_match.group(1).strip() if title_match else f"Breaking News {script_num}"
            theme = theme_match.group(1).strip() if theme_match else "General Updates"
            
            clean = re.sub(r'TITLE:.*?\n', '', content, flags=re.IGNORECASE)
            clean = re.sub(r'THEME:.*?\n', '', clean, flags=re.IGNORECASE)
            clean = re.sub(r'WORD COUNT:.*?\n', '', clean, flags=re.IGNORECASE)
            clean = re.sub(r'═+', '', clean).strip()
            
            scripts.append({
                'number': int(script_num),
                'title': title,
                'theme': theme,
                'content': clean,
                'word_count': len(clean.split())
            })
    
    return scripts[:num_scripts]

def upload_to_sheets(scripts, video_count, credibility):
    """Upload to Google Sheets"""
    try:
        SCOPES = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        
        creds_dict = json.loads(GOOGLE_CREDS_JSON)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        client = gspread.authorize(creds)
        
        try:
            spreadsheet = client.open(GOOGLE_SHEET_NAME)
        except:
            spreadsheet = client.create(GOOGLE_SHEET_NAME)
            spreadsheet.share('', perm_type='anyone', role='reader')
        
        try:
            worksheet = spreadsheet.worksheet("Scripts")
        except:
            worksheet = spreadsheet.add_worksheet(title="Scripts", rows=1000, cols=10)
            headers = [
                'Timestamp', 'Script Number', 'Title', 'Theme', 
                'Script Content', 'Word Count', 'Videos Processed',
                'Credibility', 'Status'
            ]
            worksheet.update('A1:I1', [headers])
            worksheet.format('A1:I1', {
                'backgroundColor': {'red': 0.2, 'green': 0.6, 'blue': 0.9},
                'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
                'horizontalAlignment': 'CENTER'
            })
        
        existing = worksheet.get_all_values()
        next_row = len(existing) + 1
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        rows = []
        for s in scripts:
            rows.append([
                timestamp, s['number'], s['title'], s['theme'],
                s['content'], s['word_count'], video_count,
                credibility, 'Ready for Use'
            ])
        
        if rows:
            worksheet.update(f'A{next_row}', rows)
            worksheet.columns_auto_resize(0, 9)
        
        print(f"   ✅ Uploaded {len(scripts)} scripts to Google Sheets")
        return spreadsheet.url
        
    except Exception as e:
        raise Exception(f"Sheet upload error: {str(e)}")

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        'status': 'online',
        'service': 'Instagram Reels Script Generator API',
        'version': '5.0.0 - FREE Pipeline',
        'pipeline': {
            'download': 'yt-dlp',
            'transcription': 'faster-whisper (base model)',
            'ai_processing': 'Perplexity Sonar Pro API',
            'storage': 'Google Sheets'
        }
    }), 200

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'config': {
            'perplexity_api_configured': bool(PERPLEXITY_API_KEY),
            'google_sheets_configured': bool(GOOGLE_CREDS_JSON),
            'whisper_model': 'faster-whisper base'
        }
    }), 200

@app.route('/generate', methods=['POST'])
def generate_scripts():
    try:
        if not PERPLEXITY_API_KEY:
            return jsonify({'status': 'error', 'message': 'PERPLEXITY_API_KEY not configured'}), 500
        
        if not GOOGLE_CREDS_JSON:
            return jsonify({'status': 'error', 'message': 'GOOGLE_CREDS_JSON not configured'}), 500
        
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'No JSON data provided'}), 400
        
        video_urls = data.get('video_urls', [])
        num_scripts = data.get('num_scripts', 2)
        
        if not video_urls or not isinstance(video_urls, list):
            return jsonify({'status': 'error', 'message': 'Invalid video_urls'}), 400
        
        if num_scripts < 1 or num_scripts > 5:
            return jsonify({'status': 'error', 'message': 'num_scripts must be 1-5'}), 400
        
        print(f"\n{'='*60}")
        print(f"📥 NEW REQUEST: {len(video_urls)} videos, {num_scripts} scripts")
        print(f"{'='*60}\n")
        
        all_summaries = []
        processed_count = 0
        
        for idx, url in enumerate(video_urls[:5]):
            video_id = extract_video_id(url)
            if not video_id:
                continue
            
            try:
                print(f"📹 Video {idx+1}/{len(video_urls)}: {video_id}")
                
                audio_file = download_video_audio(video_id)
                if not audio_file:
                    continue
                
                transcript, lang = transcribe_with_whisper(audio_file)
                if not transcript:
                    continue
                
                summary = create_ai_summary(transcript, video_id)
                all_summaries.append(summary)
                processed_count += 1
                
                print(f"✅ Video {idx+1} processed\n")
                time.sleep(2)
                
            except Exception as e:
                print(f"❌ Error video {idx+1}: {str(e)}\n")
                continue
        
        if processed_count == 0:
            return jsonify({'status': 'error', 'message': 'No videos processed'}), 400
        
        print(f"✅ Processed {processed_count} videos\n")
        print("🔍 Verifying news...")
        
        all_headlines = []
        for name, url in NEWS_SOURCES.items():
            headlines = scrape_news_headlines(url, name)
            all_headlines.extend(headlines)
            print(f"   📰 {name}: {len(headlines)} headlines")
        
        print()
        time.sleep(1)
        
        verification = verify_news(all_summaries, all_headlines)
        cred_match = re.search(r'CREDIBILITY[:\s]*(\d+)%', verification)
        credibility = cred_match.group(1) + '%' if cred_match else 'N/A'
        
        print(f"📊 Credibility: {credibility}\n")
        time.sleep(1)
        
        print(f"🎬 Generating {num_scripts} scripts...")
        raw_scripts = create_instagram_scripts(all_summaries, num_scripts, verification)
        parsed = parse_scripts(raw_scripts, num_scripts)
        
        print(f"\n✅ Generated {len(parsed)} scripts")
        for s in parsed:
            print(f"   Script {s['number']}: {s['word_count']} words - {s['title']}")
        
        print(f"\n📤 Uploading to Sheets...")
        sheet_url = upload_to_sheets(parsed, processed_count, credibility)
        
        print(f"✅ Done: {sheet_url}\n{'='*60}\n")
        
        return jsonify({
            'status': 'success',
            'message': 'Scripts generated successfully!',
            'data': {
                'videos_processed': processed_count,
                'scripts_generated': len(parsed),
                'sheet_url': sheet_url,
                'credibility': credibility,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'scripts': [
                    {
                        'number': s['number'],
                        'title': s['title'],
                        'theme': s['theme'],
                        'word_count': s['word_count'],
                        'content_preview': s['content'][:200] + '...'
                    } for s in parsed
                ]
            }
        }), 200
        
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}\n")
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 7860))
    app.run(host='0.0.0.0', port=port, debug=False)
