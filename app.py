from flask import Flask, request, jsonify
from flask_cors import CORS
from youtube_transcript_api import YouTubeTranscriptApi
from groq import Groq
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
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "Instagram Scripts")
WEBSHARE_PROXY = os.getenv("WEBSHARE_PROXY")

NEWS_SOURCES = {
    "Lokmat Maharashtra": "https://www.lokmat.com/maharashtra/",
    "TV9 Marathi": "https://www.tv9marathi.com/",
    "ABP Majha": "https://marathi.abplive.com/"
}


def extract_video_id(url):
    """Extract video ID from YouTube URL"""
    match = re.search(r'(?:v=|\/)([a-zA-Z0-9_-]{11})', url)
    return match.group(1) if match else None


def get_summary(text, max_sentences=8):
    """Extract key sentences from Hindi news"""
    sentences = [s.strip() for s in text.replace('!', '.').replace('?', '.').split('.') if len(s.strip()) > 30]
    keywords = ['सुप्रीम', 'कोर्ट', 'मोदी', 'सरकार', 'बोले', 'कहा', 'नए', 'नियम', 'बीजेपी', 'कांग्रेस', 'यूजीसी', 'पवार']
    scored = [(s, sum(1 for k in keywords if k in s)) for s in sentences[:60]]
    
    seen = set()
    top = []
    for s, score in sorted(scored, key=lambda x: (x[1], len(x[0])), reverse=True):
        if s not in seen and len(top) < max_sentences:
            top.append(s)
            seen.add(s)
    return top


def get_transcript_with_retry(video_id, max_retries=3):
    """Fetch transcript with proxy - ISOLATED from Groq"""
    
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                print(f"🔄 Retry attempt {attempt + 1}/{max_retries}...")
                time.sleep(2)
            
            # Build the URL manually and fetch with requests+proxy
            if WEBSHARE_PROXY:
                print(f"   ✅ Using Webshare proxy: {WEBSHARE_PROXY.split('@')[1]}")
                proxies = {
                    'http': f'http://{WEBSHARE_PROXY}',
                    'https': f'http://{WEBSHARE_PROXY}'
                }
            else:
                print(f"   ⚠️ No proxy configured!")
                proxies = None
            
            # Try both languages
            for lang_code in ['hi', 'en']:
                try:
                    print(f"   Trying {lang_code}...")
                    
                    # Manually fetch transcript JSON from YouTube
                    url = f"https://www.youtube.com/api/timedtext?lang={lang_code}&v={video_id}&fmt=json3"
                    
                    response = requests.get(
                        url,
                        proxies=proxies,
                        headers={'User-Agent': 'Mozilla/5.0'},
                        timeout=30
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        
                        if 'events' in data:
                            texts = []
                            for event in data.get('events', []):
                                if 'segs' in event:
                                    for seg in event['segs']:
                                        if 'utf8' in seg:
                                            texts.append(seg['utf8'])
                            
                            if texts:
                                full_text = ' '.join(texts)
                                print(f"   ✅ Got transcript: {len(full_text)} chars in {lang_code}")
                                return full_text, lang_code
                    
                    # Fallback to youtube-transcript-api
                    from youtube_transcript_api import YouTubeTranscriptApi
                    ytt_api = YouTubeTranscriptApi()
                    transcript_data = ytt_api.fetch(video_id, languages=[lang_code])
                    full_text = ' '.join([entry.text for entry in transcript_data])
                    print(f"   ✅ Got transcript: {len(full_text)} chars in {lang_code}")
                    return full_text, lang_code
                    
                except Exception as e:
                    print(f"   {lang_code} failed: {str(e)[:100]}")
                    continue
            
            raise Exception("No transcript available")
            
        except Exception as e:
            print(f"   ❌ Attempt {attempt + 1} failed: {str(e)[:150]}")
            if attempt == max_retries - 1:
                raise e
            continue
    
    return None, None


def create_ai_summary(transcript, video_id, language):
    """Create AI summary - NO PROXY for Groq"""
    try:
        # Make ABSOLUTELY SURE requests.get is not patched
        import importlib
        importlib.reload(requests)
        
        # Now create Groq client with clean requests
        client = Groq(api_key=GROQ_API_KEY)
        truncated = transcript[:6000] + "..." if len(transcript) > 6000 else transcript
        
        prompt = f"""You are a Hindi news summarizer. Extract 8-10 key news stories from this video.

VIDEO ID: {video_id}
LANGUAGE: {language}

TRANSCRIPT:
{truncated}

TASK: Extract ALL important news stories with MAXIMUM details

For each story:
- Write 3-4 sentences in Hindi
- Include: what happened, who is involved, key facts (dates, numbers, places, quotes)
- Add background context if relevant
- Focus on concrete news (politics, accidents, court cases, schemes, protests, etc.)

FORMAT:
[1] Story headline - Detailed explanation in 3-4 sentences with all facts
[2] Next story - Detailed explanation with numbers, names, places
[3] Continue...

Write 8-10 stories. Keep total summary under 1200 words. Write in simple Hindi."""

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are an expert Hindi news summarizer. Be detailed and comprehensive."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=2000
        )
        
        summary = completion.choices[0].message.content.strip()
        print(f"   ✅ AI summary created: {len(summary)} characters")
        return summary
        
    except Exception as e:
        print(f"   ⚠️ AI summary failed: {str(e)}")
        return '\n'.join(get_summary(transcript, max_sentences=8))


def scrape_news_headlines(url, source_name):
    """Scrape headlines"""
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
                if len(text) > 20 and len(text) < 200:
                    headlines.append(text)
        
        return list(set(headlines))[:30]
    except Exception as e:
        print(f"   ⚠️ Scraping {source_name} failed: {str(e)}")
        return []


def verify_news_with_groq(all_summaries, scraped_news):
    """Verify news - NO PROXY for Groq"""
    try:
        # Make ABSOLUTELY SURE requests.get is not patched
        import importlib
        importlib.reload(requests)
        
        # Now create Groq client with clean requests
        client = Groq(api_key=GROQ_API_KEY)
        
        video_text = "\n\n".join([f"VIDEO {i+1}:\n{s[:800]}" for i, s in enumerate(all_summaries)])
        news_text = '\n'.join(scraped_news[:25])
        
        prompt = f"""Compare video summaries with current headlines. Provide credibility score.

VIDEO SUMMARIES:
{video_text[:4000]}

CURRENT HEADLINES:
{news_text[:2000]}

Format:
✅ VERIFIED: [List]
⚠️ UNVERIFIED: [List]
📊 CREDIBILITY: X%"""

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a news fact-checker."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=1000
        )
        
        result = completion.choices[0].message.content
        print(f"   ✅ Verification completed")
        return result
        
    except Exception as e:
        print(f"   ⚠️ Verification failed: {str(e)}")
        return "Verification unavailable"


def create_instagram_scripts(all_summaries, num_scripts, verification):
    """Generate LONG viral scripts - NO PROXY for Groq"""
    try:
        # Make ABSOLUTELY SURE requests.get is not patched
        import importlib
        importlib.reload(requests)
        
        # Now create Groq client with clean requests
        client = Groq(api_key=GROQ_API_KEY)
        
        combined = "\n\n".join([f"VIDEO {i+1}:\n{s[:900]}" for i, s in enumerate(all_summaries)])
        
        themes = [
            "Supreme Court & Political Drama",
            "Maharashtra Politics & Leaders", 
            "Economic Growth & Trade Deals",
            "Social Issues & Public Protests",
            "Regional News & Controversies"
        ]
        
        prompt = f"""You are India's #1 VIRAL Instagram influencer scriptwriter.

Create {num_scripts} SUPER LONG, SUPER ENGAGING Reels scripts in HINGLISH.

NEWS SUMMARIES: {combined[:5000]}
VERIFICATION: {verification[:600]}

⚠️ CRITICAL: Each script MUST be 450-550 WORDS minimum!
⚠️ Each script must cover 7-9 DIFFERENT stories with FULL details!

Generate all {num_scripts} scripts NOW with unique content in each."""

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system", 
                    "content": "You are India's #1 viral Instagram creator. Scripts MUST be 500+ words with 7-9 detailed stories each."
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.95,
            max_tokens=6000
        )
        
        result = completion.choices[0].message.content
        print(f"   ✅ Scripts generated: {len(result)} characters")
        return result
        
    except Exception as e:
        print(f"   ⚠️ Script generation failed: {str(e)}")
        return f"Error: {str(e)}"

def parse_scripts(raw_text, num_scripts):
    """Parse scripts"""
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
                'Timestamp', 
                'Script Number', 
                'Title', 
                'Theme', 
                'Script Content', 
                'Word Count',
                'Videos Processed',
                'Credibility',
                'Status'
            ]
            worksheet.update('A1', [headers])
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
                timestamp,
                s['number'],
                s['title'],
                s['theme'],
                s['content'],
                s['word_count'],
                video_count,
                credibility,
                'Ready for Use'
            ])
        
        if rows:
            worksheet.update(f'A{next_row}', rows)
            worksheet.columns_auto_resize(0, 9)
        
        print(f"   ✅ Uploaded {len(scripts)} scripts to Google Sheets")
        return spreadsheet.url
        
    except Exception as e:
        raise Exception(f"Sheet upload error: {str(e)}")


# ========== API ENDPOINTS ==========

@app.route('/', methods=['GET'])
def home():
    """Health check endpoint"""
    return jsonify({
        'status': 'online',
        'service': 'Instagram Reels Script Generator API',
        'version': '2.0.1',
        'endpoints': {
            'POST /generate': 'Generate long viral scripts from YouTube videos',
            'GET /health': 'Check API health'
        },
        'features': {
            'script_length': '450-550 words per script',
            'stories_per_script': '7-9 different stories',
            'language': 'Hinglish (55% Hindi + 45% English)',
            'tone': 'Conversational influencer style',
            'proxy_enabled': bool(WEBSHARE_PROXY)
        }
    }), 200


@app.route('/health', methods=['GET'])
def health():
    """Health check"""
    has_groq = bool(GROQ_API_KEY)
    has_google = bool(GOOGLE_CREDS_JSON)
    has_proxy = bool(WEBSHARE_PROXY)
    
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'config': {
            'groq_api_configured': has_groq,
            'google_sheets_configured': has_google,
            'proxy_configured': has_proxy,
            'sheet_name': GOOGLE_SHEET_NAME
        }
    }), 200


@app.route('/generate', methods=['POST'])
def generate_scripts():
    """Main endpoint to generate scripts"""
    
    try:
        if not GROQ_API_KEY:
            return jsonify({
                'status': 'error',
                'message': 'GROQ_API_KEY not configured in environment variables'
            }), 500
        
        if not GOOGLE_CREDS_JSON:
            return jsonify({
                'status': 'error',
                'message': 'GOOGLE_CREDS_JSON not configured in environment variables'
            }), 500
        
        data = request.get_json()
        
        if not data:
            return jsonify({
                'status': 'error',
                'message': 'No JSON data provided'
            }), 400
        
        video_urls = data.get('video_urls', [])
        num_scripts = data.get('num_scripts', 2)
        
        if not video_urls or len(video_urls) == 0:
            return jsonify({
                'status': 'error',
                'message': 'Please provide at least 1 video URL'
            }), 400
        
        if not isinstance(video_urls, list):
            return jsonify({
                'status': 'error',
                'message': 'video_urls must be a list'
            }), 400
        
        if num_scripts < 1 or num_scripts > 5:
            return jsonify({
                'status': 'error',
                'message': 'num_scripts must be between 1 and 5'
            }), 400
        
        print(f"📥 Processing {len(video_urls)} videos...")
        
        all_summaries = []
        processed_count = 0
        
        for idx, url in enumerate(video_urls[:5]):
            video_id = extract_video_id(url)
            if not video_id:
                print(f"⚠️ Invalid URL: {url}")
                continue
            
            try:
                print(f"📹 Processing video {idx+1}/{len(video_urls)}: {video_id}")
                
                transcript, lang = get_transcript_with_retry(video_id)
                if not transcript:
                    print(f"⚠️ No transcript for {video_id}")
                    continue
                
                summary = create_ai_summary(transcript, video_id, lang)
                all_summaries.append(summary)
                processed_count += 1
                
                print(f"✅ Video {idx+1} processed successfully")
                
            except Exception as e:
                print(f"❌ Error processing video {idx+1}: {str(e)}")
                continue
        
        if processed_count == 0:
            return jsonify({
                'status': 'error',
                'message': 'No videos could be processed. Check if videos have captions.'
            }), 400
        
        print(f"✅ Processed {processed_count} videos")
        
        print("🔍 Verifying news...")
        all_headlines = []
        for source_name, source_url in NEWS_SOURCES.items():
            headlines = scrape_news_headlines(source_url, source_name)
            all_headlines.extend(headlines)
            print(f"   📰 {source_name}: {len(headlines)} headlines")
        
        verification = verify_news_with_groq(all_summaries, all_headlines)
        
        cred_match = re.search(r'CREDIBILITY[:\s]*(\d+)%', verification)
        credibility = cred_match.group(1) + '%' if cred_match else 'N/A'
        
        print(f"📊 Credibility: {credibility}")
        
        print(f"🎬 Generating {num_scripts} LONG viral scripts (450-550 words each)...")
        
        raw_scripts = create_instagram_scripts(all_summaries, num_scripts, verification)
        parsed = parse_scripts(raw_scripts, num_scripts)
        
        print(f"✅ Generated {len(parsed)} scripts")
        for s in parsed:
            print(f"   Script {s['number']}: {s['word_count']} words - {s['title']}")
        
        print("📤 Uploading to Google Sheets...")
        
        sheet_url = upload_to_sheets(parsed, processed_count, credibility)
        
        print(f"✅ Uploaded to: {sheet_url}")
        
        return jsonify({
            'status': 'success',
            'message': 'Scripts generated and uploaded successfully',
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
                        'content_preview': s['content'][:200] + '...' if len(s['content']) > 200 else s['content']
                    } for s in parsed
                ]
            }
        }), 200
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


if __name__ == '__main__':
    port = int(os.getenv('PORT', 7860))
    app.run(host='0.0.0.0', port=port, debug=False)
