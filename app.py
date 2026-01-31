from flask import Flask, request, jsonify
from flask_cors import CORS
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

NEWS_SOURCES = {
    "Lokmat Maharashtra": "https://www.lokmat.com/maharashtra/",
    "TV9 Marathi": "https://www.tv9marathi.com/",
    "ABP Majha": "https://marathi.abplive.com/"
}

def extract_video_id(url):
    """Extract video ID from YouTube URL"""
    match = re.search(r'(?:v=|\/)([a-zA-Z0-9_-]{11})', url)
    return match.group(1) if match else None

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
        
        response = requests.post(url, json=payload, headers=headers, timeout=120)
        response.raise_for_status()
        
        return response.json()['choices'][0]['message']['content']
        
    except Exception as e:
        print(f"   ⚠️ Perplexity API error: {str(e)}")
        raise e

def analyze_video_with_perplexity(video_id):
    """Analyze YouTube video directly with Perplexity (no transcript needed!)"""
    try:
        youtube_url = f"https://www.youtube.com/watch?v={video_id}"
        print(f"   🎥 Analyzing video with Perplexity Pro: {video_id}...")
        
        prompt = f"""Watch and analyze this YouTube news video, then extract 8-10 key Hindi news stories with FULL details:

VIDEO URL: {youtube_url}

TASK: Extract ALL important news stories mentioned in this video

For each story:
- Write 3-4 sentences in Hindi/Hinglish
- Include: what happened, who is involved, key facts (dates, numbers, places, quotes)
- Add background context if relevant
- Focus on concrete news (politics, accidents, court cases, schemes, protests, government decisions, etc.)

FORMAT:
[1] Story headline - Detailed explanation in 3-4 sentences with all facts
[2] Next story - Detailed explanation with numbers, names, places
[3] Continue for all stories...

Write 8-10 stories. Keep total summary under 1500 words. Write in simple Hindi/Hinglish.

IMPORTANT: Watch the entire video and extract REAL news content, not just the video description."""

        summary = call_perplexity_api(prompt, max_tokens=3000)
        
        if not summary or len(summary) < 100:
            raise Exception("Summary too short or empty")
        
        print(f"   ✅ Video analyzed: {len(summary)} characters")
        return summary, 'hi'
        
    except Exception as e:
        print(f"   ❌ Perplexity analysis failed: {str(e)}")
        return None, None

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

# ========== API ENDPOINTS ==========

@app.route('/', methods=['GET'])
def home():
    """Health check endpoint"""
    return jsonify({
        'status': 'online',
        'service': 'Instagram Reels Script Generator API',
        'version': '8.0.0 - Perplexity-Only Pipeline (FINAL)',
        'endpoints': {
            'POST /generate': 'Generate viral scripts from YouTube videos',
            'GET /health': 'Check API health'
        },
        'pipeline': {
            'video_analysis': 'Perplexity Sonar Pro (watches videos directly)',
            'script_generation': 'Perplexity Sonar Pro API ($5 credit/month)',
            'storage': 'Google Sheets (FREE)'
        },
        'features': [
            'No YouTube blocking - Perplexity watches videos directly',
            'No transcripts needed - AI understands video content',
            'Uses only your Perplexity Pro subscription',
            'Generates 450-550 word scripts in Hinglish',
            'Covers 7-9 stories per script'
        ]
    }), 200

@app.route('/health', methods=['GET'])
def health():
    """Health check"""
    has_perplexity = bool(PERPLEXITY_API_KEY)
    has_google = bool(GOOGLE_CREDS_JSON)
    
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'config': {
            'perplexity_api_configured': has_perplexity,
            'google_sheets_configured': has_google,
            'sheet_name': GOOGLE_SHEET_NAME
        }
    }), 200

@app.route('/generate', methods=['POST'])
def generate_scripts():
    """Main endpoint to generate scripts"""
    
    try:
        if not PERPLEXITY_API_KEY:
            return jsonify({
                'status': 'error',
                'message': 'PERPLEXITY_API_KEY not configured. Get it from https://www.perplexity.ai/settings/api'
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
        
        print(f"\n{'='*60}")
        print(f"📥 NEW REQUEST: {len(video_urls)} videos, {num_scripts} scripts")
        print(f"🤖 Using: Perplexity Pro (watches videos directly)")
        print(f"{'='*60}\n")
        
        all_summaries = []
        processed_count = 0
        
        for idx, url in enumerate(video_urls[:5]):
            video_id = extract_video_id(url)
            if not video_id:
                print(f"⚠️ Invalid URL: {url}")
                continue
            
            try:
                print(f"📹 Processing video {idx+1}/{len(video_urls)}: {video_id}")
                
                # Analyze video with Perplexity (no transcript needed!)
                summary, lang = analyze_video_with_perplexity(video_id)
                if not summary:
                    continue
                
                all_summaries.append(summary)
                processed_count += 1
                
                print(f"✅ Video {idx+1} processed successfully\n")
                
                # Delay between videos to respect API limits
                if idx < len(video_urls) - 1:
                    time.sleep(3)
                
            except Exception as e:
                print(f"❌ Error processing video {idx+1}: {str(e)}\n")
                continue
        
        if processed_count == 0:
            return jsonify({
                'status': 'error',
                'message': 'No videos could be processed. Check video URLs and Perplexity API key.'
            }), 400
        
        print(f"✅ Processed {processed_count} videos\n")
        
        print("🔍 Verifying news...")
        all_headlines = []
        for source_name, source_url in NEWS_SOURCES.items():
            headlines = scrape_news_headlines(source_url, source_name)
            all_headlines.extend(headlines)
            print(f"   📰 {source_name}: {len(headlines)} headlines")
        
        print()
        time.sleep(2)
        
        verification = verify_news(all_summaries, all_headlines)
        
        cred_match = re.search(r'CREDIBILITY[:\s]*(\d+)%', verification)
        credibility = cred_match.group(1) + '%' if cred_match else 'N/A'
        
        print(f"📊 Credibility: {credibility}\n")
        
        time.sleep(2)
        
        print(f"🎬 Generating {num_scripts} LONG viral scripts with Perplexity Sonar Pro...")
        
        raw_scripts = create_instagram_scripts(all_summaries, num_scripts, verification)
        parsed = parse_scripts(raw_scripts, num_scripts)
        
        print(f"\n✅ Generated {len(parsed)} scripts:")
        for s in parsed:
            print(f"   Script {s['number']}: {s['word_count']} words - {s['title']}")
        
        print(f"\n📤 Uploading to Google Sheets...")
        
        sheet_url = upload_to_sheets(parsed, processed_count, credibility)
        
        print(f"✅ Uploaded to: {sheet_url}")
        print(f"\n{'='*60}")
        print(f"🎉 REQUEST COMPLETED SUCCESSFULLY!")
        print(f"{'='*60}\n")
        
        return jsonify({
            'status': 'success',
            'message': 'Scripts generated successfully using Perplexity Pro!',
            'data': {
                'videos_processed': processed_count,
                'scripts_generated': len(parsed),
                'sheet_url': sheet_url,
                'credibility': credibility,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'pipeline_used': 'Perplexity Pro (Video Analysis) → Google Sheets',
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
        print(f"\n❌ FATAL ERROR: {str(e)}\n")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 7860))
    print(f"\n🚀 Starting Instagram Reels Script Generator...")
    print(f"🎥 Video Analysis: Perplexity Pro (watches videos directly)")
    print(f"🤖 AI Processing: Perplexity Sonar Pro")
    print(f"📊 Storage: Google Sheets")
    print(f"🌐 Port: {port}")
    print(f"💡 No YouTube blocking - Perplexity understands video content!\n")
    app.run(host='0.0.0.0', port=port, debug=False)
