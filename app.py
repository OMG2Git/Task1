from flask import Flask, request, jsonify
from flask_cors import CORS
from youtube_transcript_api import YouTubeTranscriptApi
from google import genai
from google.genai.types import GenerateContentConfig
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import time
import gspread
from google.oauth2.service_account import Credentials
import json
import os

app = Flask(__name__)
CORS(app)

# ========== CONFIGURATION ==========
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "Instagram Scripts")

# Initialize Gemini client
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

NEWS_SOURCES = {
    "Lokmat Maharashtra": "https://www.lokmat.com/maharashtra/",
    "TV9 Marathi": "https://www.tv9marathi.com/",
    "ABP Majha": "https://marathi.abplive.com/"
}

def extract_video_id(url):
    """Extract video ID from YouTube URL"""
    match = re.search(r'(?:v=|\/)([a-zA-Z0-9_-]{11})', url)
    return match.group(1) if match else None

def get_transcript_simple(video_id, max_retries=3):
    """
    Get transcript using youtube-transcript-api (NO PROXY)
    Railway US servers should not be blocked by YouTube
    """
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                print(f"🔄 Retry attempt {attempt + 1}/{max_retries}...")
                time.sleep(2)
            
            print(f"   📝 Fetching transcript for {video_id}...")
            
            # Try both Hindi and English
            for lang_code in ['hi', 'mr', 'en']:
                try:
                    print(f"   Trying {lang_code}...")
                    transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=[lang_code])
                    transcript_text = ' '.join([entry['text'] for entry in transcript_list])
                    
                    if len(transcript_text) > 100:
                        print(f"   ✅ Got transcript: {len(transcript_text)} chars in {lang_code}")
                        return transcript_text, lang_code
                        
                except Exception as e:
                    print(f"   {lang_code} failed: {str(e)[:100]}")
                    continue
            
            raise Exception("No transcript available in any language")
            
        except Exception as e:
            print(f"   ❌ Attempt {attempt + 1} failed: {str(e)[:150]}")
            if attempt == max_retries - 1:
                raise e
            time.sleep(3)
            continue
    
    return None, None

def create_ai_summary_with_gemini(transcript, video_id, language):
    """Create AI summary using Gemini 1.5 Flash"""
    try:
        truncated = transcript[:15000] if len(transcript) > 15000 else transcript
        
        prompt = f"""You are a Hindi news summarizer. Extract 8-10 key news stories from this video transcript.

VIDEO ID: {video_id}
LANGUAGE: {language}

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

        response = gemini_client.models.generate_content(
            model='gemini-1.5-flash-latest',
            contents=prompt,
            config=GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=2500
            )
        )
        
        summary = response.text.strip()
        print(f"   ✅ AI summary created: {len(summary)} characters")
        return summary
        
    except Exception as e:
        print(f"   ⚠️ AI summary failed: {str(e)}")
        sentences = [s.strip() for s in transcript.replace('!', '.').replace('?', '.').split('.') if len(s.strip()) > 30]
        return '\n'.join(sentences[:15])

def scrape_news_headlines(url, source_name):
    """Scrape headlines from news websites"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
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
        
        return list(set(headlines))[:30]
    except Exception as e:
        print(f"   ⚠️ Scraping {source_name} failed: {str(e)}")
        return []

def verify_news_with_gemini(all_summaries, scraped_news):
    """Verify news credibility using Gemini 1.5 Flash"""
    try:
        video_text = "\n\n".join([f"VIDEO {i+1}:\n{s[:1000]}" for i, s in enumerate(all_summaries)])
        news_text = '\n'.join(scraped_news[:30])
        
        prompt = f"""You are a professional news fact-checker. Compare these video summaries with current headlines and provide a credibility score.

VIDEO SUMMARIES:
{video_text[:5000]}

CURRENT NEWS HEADLINES:
{news_text[:2500]}

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

        response = gemini_client.models.generate_content(
            model='gemini-1.5-flash-latest',
            contents=prompt,
            config=GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=1500
            )
        )
        
        result = response.text.strip()
        print(f"   ✅ Verification completed")
        return result
        
    except Exception as e:
        print(f"   ⚠️ Verification failed: {str(e)}")
        return "Verification unavailable"

def create_instagram_scripts_with_gemini(all_summaries, num_scripts, verification):
    """Generate viral Instagram scripts using Gemini 1.5 Flash"""
    try:
        combined = "\n\n".join([f"VIDEO {i+1}:\n{s[:1000]}" for i, s in enumerate(all_summaries)])
        
        prompt = f"""You are India's #1 VIRAL Instagram Reels scriptwriter specializing in Hindi news content.

Create {num_scripts} SUPER ENGAGING, SUPER LONG Instagram Reels scripts in HINGLISH (55% Hindi + 45% English).

NEWS SUMMARIES:
{combined[:6000]}

VERIFICATION:
{verification[:800]}

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

        response = gemini_client.models.generate_content(
            model='gemini-1.5-flash-latest',
            contents=prompt,
            config=GenerateContentConfig(
                temperature=0.95,
                max_output_tokens=8000
            )
        )
        
        result = response.text.strip()
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
        'service': 'Instagram Reels Script Generator',
        'version': '4.0.0',
        'transcript': 'youtube-transcript-api (no proxy)',
        'ai': 'Gemini 1.5 Flash (text processing only)'
    }), 200

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'gemini_configured': bool(GEMINI_API_KEY),
        'sheets_configured': bool(GOOGLE_CREDS_JSON)
    }), 200

@app.route('/generate', methods=['POST'])
def generate_scripts():
    try:
        if not GEMINI_API_KEY or not GOOGLE_CREDS_JSON:
            return jsonify({'status': 'error', 'message': 'Missing API keys'}), 500
        
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'No JSON data'}), 400
        
        video_urls = data.get('video_urls', [])
        num_scripts = data.get('num_scripts', 2)
        
        if not video_urls or not isinstance(video_urls, list):
            return jsonify({'status': 'error', 'message': 'Invalid video_urls'}), 400
        
        if num_scripts < 1 or num_scripts > 5:
            return jsonify({'status': 'error', 'message': 'num_scripts must be 1-5'}), 400
        
        print(f"📥 Processing {len(video_urls)} videos...")
        
        all_summaries = []
        processed_count = 0
        
        for idx, url in enumerate(video_urls[:5]):
            video_id = extract_video_id(url)
            if not video_id:
                continue
            
            try:
                print(f"📹 Video {idx+1}/{len(video_urls)}: {video_id}")
                
                transcript, lang = get_transcript_simple(video_id)
                if not transcript:
                    continue
                
                summary = create_ai_summary_with_gemini(transcript, video_id, lang)
                all_summaries.append(summary)
                processed_count += 1
                
                print(f"✅ Video {idx+1} processed")
                time.sleep(2)
                
            except Exception as e:
                print(f"❌ Error video {idx+1}: {str(e)}")
                continue
        
        if processed_count == 0:
            return jsonify({'status': 'error', 'message': 'No videos processed'}), 400
        
        print("🔍 Verifying news...")
        all_headlines = []
        for name, url in NEWS_SOURCES.items():
            headlines = scrape_news_headlines(url, name)
            all_headlines.extend(headlines)
            print(f"   📰 {name}: {len(headlines)} headlines")
        
        time.sleep(2)
        verification = verify_news_with_gemini(all_summaries, all_headlines)
        cred_match = re.search(r'CREDIBILITY[:\s]*(\d+)%', verification)
        credibility = cred_match.group(1) + '%' if cred_match else 'N/A'
        
        time.sleep(2)
        print(f"🎬 Generating {num_scripts} scripts...")
        raw_scripts = create_instagram_scripts_with_gemini(all_summaries, num_scripts, verification)
        parsed = parse_scripts(raw_scripts, num_scripts)
        
        print("📤 Uploading to Sheets...")
        sheet_url = upload_to_sheets(parsed, processed_count, credibility)
        
        return jsonify({
            'status': 'success',
            'message': 'Scripts generated!',
            'data': {
                'videos_processed': processed_count,
                'scripts_generated': len(parsed),
                'sheet_url': sheet_url,
                'credibility': credibility,
                'scripts': [{'number': s['number'], 'title': s['title'], 'word_count': s['word_count']} for s in parsed]
            }
        }), 200
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 7860))
    app.run(host='0.0.0.0', port=port, debug=False)
