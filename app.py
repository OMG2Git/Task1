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
                    "content": "You are an expert at analyzing YouTube video content and extracting detailed information from what is actually said and shown in videos."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": max_tokens,
            "temperature": 0.2,
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
    """Analyze YouTube video content using Perplexity's video understanding"""
    try:
        youtube_url = f"https://www.youtube.com/watch?v={video_id}"
        print(f"   🎥 Analyzing video with Perplexity Pro: {video_id}...")
        
        prompt = f"""CRITICAL INSTRUCTIONS: You MUST watch and analyze the ACTUAL CONTENT of this specific YouTube video. Do NOT use web search or external news sources.

VIDEO URL TO ANALYZE: {youtube_url}

YOUR TASK:
1. Watch this specific video from start to finish
2. Extract ONLY the topics, arguments, and information presented IN THIS VIDEO
3. Identify the main subject and all key points discussed by the speaker
4. Note specific examples, statistics, names, and incidents mentioned in the video

WHAT TO EXTRACT:
- Main theme/subject of the video
- Key arguments or points made by the speaker
- Specific examples, case studies, or incidents mentioned
- Statistics, numbers, dates, names referenced
- Any controversies, policies, or events discussed
- Speaker's perspective and opinions

OUTPUT FORMAT:
Write a detailed summary (800-1200 words) in Hindi/Hinglish covering:

[MAIN TOPIC]
What is this video primarily about?

[KEY POINTS]
List 8-10 major points discussed in the video with full context:
1. [Point with details]
2. [Point with details]
...

[SPECIFIC EXAMPLES]
List specific examples, incidents, or cases mentioned

[CONCLUSIONS]
What conclusions or calls-to-action does the speaker make?

CRITICAL RULES:
- Extract information ONLY from this video content
- Do NOT add current news or web search results
- Do NOT make up stories not in the video
- Focus on what the speaker actually says
- Include direct quotes if possible
- Write in simple Hindi/Hinglish mix

VIDEO: {youtube_url}

BEGIN ANALYSIS NOW."""

        summary = call_perplexity_api(prompt, max_tokens=3500)
        
        if not summary or len(summary) < 100:
            raise Exception("Summary too short or empty")
        
        print(f"   ✅ Video analyzed: {len(summary)} characters")
        return summary, 'hi'
        
    except Exception as e:
        print(f"   ❌ Perplexity analysis failed: {str(e)}")
        return None, None


def scrape_news_headlines(url, source_name):
    """Scrape headlines from news websites - ONLY FOR VERIFICATION"""
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
    """Verify if video content matches current news - for credibility only"""
    try:
        video_text = "\n\n".join([f"VIDEO {i+1}:\n{s[:800]}" for i, s in enumerate(all_summaries)])
        news_text = '\n'.join(scraped_news[:30])
        
        prompt = f"""Compare the video content with current headlines to assess if topics are current/relevant.

VIDEO CONTENT:
{video_text[:4000]}

CURRENT HEADLINES (for reference only):
{news_text[:2000]}

Rate the RELEVANCE of video content to current events (0-100%)
This is just to check if video discusses recent/current topics, NOT to add new stories.

Format:
RELEVANCE SCORE: X%
Brief explanation"""

        result = call_perplexity_api(prompt, max_tokens=800)
        print(f"   ✅ Verification completed")
        return result
        
    except Exception as e:
        print(f"   ⚠️ Verification failed: {str(e)}")
        return "Verification unavailable"


def create_instagram_scripts(all_summaries, num_scripts, verification):
    """Generate viral Instagram scripts using Perplexity Sonar API"""
    try:
        combined = "\n\n".join([f"VIDEO {i+1}:\n{s}" for i, s in enumerate(all_summaries)])
        
        prompt = f"""You are India's top VIRAL Instagram Reels scriptwriter for Hindi news content.
Write in natural Hinglish (around 60% Hindi, 40% English), like a high-energy news influencer talking directly to followers.

You will create {num_scripts} different Instagram Reels scripts based ONLY on the video content below.

VIDEO CONTENT TO USE:
{combined[:8000]}

CRITICAL RULES FOR CONTENT:
- Use ONLY information from the video summaries above
- DO NOT add external news, web search results, or current events
- Extract the ACTUAL topics discussed in the videos
- If video discusses one main topic (like education crisis), break it into subtopics for the script
- Stay true to the speaker's arguments and examples

═══════════════════════════════════════════════════════════
STRICT OUTPUT FORMAT RULES:
═══════════════════════════════════════════════════════════

1. Each script MUST be ONE continuous monologue - NOT bullets, NOT numbered lists
2. Do NOT use "Story 1", "Story 2" labels or bullet points
3. Do NOT include citation markers like [1], [2], [3], [4], [5]
4. Do NOT use section labels like "Hook:", "Opening:", "Story:"
5. Write as pure spoken text that flows naturally from start to finish
6. Structure it as continuous paragraphs with smooth transitions

═══════════════════════════════════════════════════════════
CONTENT & TONE REQUIREMENTS:
═══════════════════════════════════════════════════════════

LENGTH: 450-550 words minimum per script (MANDATORY)

TONE: Talk like a young, energetic news influencer speaking to followers
- Use phrases like: "dosto", "bhai log", "suno yaar", "dekho", "arrey"
- Mix emotions: shock, anger, concern, hope
- Sound passionate and authentic
- Address audience directly

COVERAGE: Extract 7-9 key points from the video content:
- Main issue/controversy discussed
- Specific examples or incidents mentioned
- Statistics or facts cited
- People or organizations named
- Government policies or decisions discussed
- Speaker's arguments and perspective
- Impact on common people

TRANSITIONS: Connect points smoothly:
- "Aur sunao agle point..."
- "Lekin baat yahin nahi rukti..."
- "Ab samjho asli mudda kya hai..."
- "Dekhiye kya hua actually..."

EMOJIS: Use naturally (🔥😤💪🎯🚨) but sparingly

═══════════════════════════════════════════════════════════
SCRIPT STRUCTURE:
═══════════════════════════════════════════════════════════

OPENING (20-30 words): Hook based on video's main topic
- Reference the core issue discussed
- Create curiosity
- Sound urgent/important

MAIN BODY (370-450 words): Flow through main points from video
- Present each key argument or example
- Add context and explanation
- Keep energy high
- Use speaker's perspective
- Include specific details mentioned

CLOSING (30-40 words): Call to action
- Ask for opinions
- Encourage discussion
- CTA: "Comment mein batao, like karo, follow karo"

═══════════════════════════════════════════════════════════
OUTPUT FORMAT:
═══════════════════════════════════════════════════════════

═══════════════════════
SCRIPT [NUMBER]
═══════════════════════
TITLE: [Catchy Hinglish title based on video topic]
THEME: [Main subject from video]
WORD COUNT: [Count]

[CONTINUOUS SCRIPT - flows as one spoken piece, based ONLY on video content]

═══════════════════════

CRITICAL REMINDERS:
- NO citation numbers [1], [2], [3]
- NO "Story 1:", "Point 1:" labels
- Use ONLY content from the video summaries provided
- Make it conversational and authentic
- Sound like you're talking to friends about something important

Now create {num_scripts} unique scripts based on the VIDEO CONTENT above."""

        result = call_perplexity_api(prompt, max_tokens=10000)
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
            
            # Remove any remaining citation markers
            clean = re.sub(r'\[\d+\]', '', clean)
            
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
        print(f"   🔑 Authenticating with Google...")
        SCOPES = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        
        creds_dict = json.loads(GOOGLE_CREDS_JSON)
        print(f"   ✅ Credentials loaded: {creds_dict.get('project_id', 'N/A')}")
        
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        client = gspread.authorize(creds)
        print(f"   ✅ Google Sheets client authorized")
        
        try:
            spreadsheet = client.open(GOOGLE_SHEET_NAME)
            print(f"   ✅ Opened existing sheet: {GOOGLE_SHEET_NAME}")
        except Exception as e:
            print(f"   ⚠️ Sheet not found, creating new: {GOOGLE_SHEET_NAME}")
            spreadsheet = client.create(GOOGLE_SHEET_NAME)
            spreadsheet.share('', perm_type='anyone', role='reader')
            print(f"   ✅ Created new sheet")
        
        try:
            worksheet = spreadsheet.worksheet("Scripts")
            print(f"   ✅ Found 'Scripts' worksheet")
        except Exception as e:
            print(f"   ⚠️ 'Scripts' worksheet not found, creating...")
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
            print(f"   ✅ Created 'Scripts' worksheet with headers")
        
        existing = worksheet.get_all_values()
        next_row = len(existing) + 1
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        print(f"   📝 Preparing {len(scripts)} rows for row {next_row}...")
        
        rows = []
        for s in scripts:
            rows.append([
                timestamp, s['number'], s['title'], s['theme'],
                s['content'], s['word_count'], video_count,
                credibility, 'Ready for Use'
            ])
        
        if rows:
            print(f"   📤 Uploading {len(rows)} rows...")
            worksheet.update(f'A{next_row}', rows)
            worksheet.columns_auto_resize(0, 9)
            print(f"   ✅ Upload complete!")
        
        sheet_url = spreadsheet.url
        print(f"   🔗 Sheet URL: {sheet_url}")
        return sheet_url
        
    except Exception as e:
        error_msg = f"Sheet upload error: {str(e)}"
        print(f"   ❌ {error_msg}")
        import traceback
        print(f"   📋 Full traceback:\n{traceback.format_exc()}")
        raise Exception(error_msg)


# ========== API ENDPOINTS ==========


@app.route('/', methods=['GET'])
def home():
    """Health check endpoint"""
    return jsonify({
        'status': 'online',
        'service': 'Instagram Reels Script Generator API',
        'version': '9.0.0 - TRUE Video Analysis (Fixed)',
        'endpoints': {
            'POST /generate': 'Generate viral scripts from YouTube videos',
            'GET /health': 'Check API health'
        },
        'pipeline': {
            'video_analysis': 'Perplexity Sonar Pro (analyzes actual video content)',
            'script_generation': 'Based ONLY on video content',
            'verification': 'Headlines used only for relevance check',
            'storage': 'Google Sheets'
        },
        'features': [
            'Analyzes ACTUAL video content (not web search)',
            'Scripts based purely on what speaker says',
            'No random news insertion',
            'Generates 450-550 word conversational scripts',
            'Continuous monologue format (no bullets)'
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
        print(f"🤖 Using: Perplexity Sonar Pro (TRUE video content analysis)")
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
                
                # Analyze video with strict instructions
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
        
        print("🔍 Checking relevance (headlines for reference only)...")
        all_headlines = []
        for source_name, source_url in NEWS_SOURCES.items():
            headlines = scrape_news_headlines(source_url, source_name)
            all_headlines.extend(headlines)
            print(f"   📰 {source_name}: {len(headlines)} headlines")
        
        print()
        time.sleep(2)
        
        verification = verify_news(all_summaries, all_headlines)
        
        cred_match = re.search(r'RELEVANCE[:\s]*(\d+)%', verification)
        credibility = cred_match.group(1) + '%' if cred_match else 'N/A'
        
        print(f"📊 Relevance: {credibility}\n")
        
        time.sleep(2)
        
        print(f"🎬 Generating {num_scripts} viral scripts based on VIDEO CONTENT ONLY...")
        
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
            'message': 'Scripts generated from actual video content!',
            'data': {
                'videos_processed': processed_count,
                'scripts_generated': len(parsed),
                'sheet_url': sheet_url,
                'relevance': credibility,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'pipeline_used': 'Perplexity Video Analysis → Script Generation → Google Sheets',
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
    print(f"🎥 Video Analysis: Perplexity Sonar Pro (ACTUAL video content)")
    print(f"🤖 Script Generation: Based ONLY on video content")
    print(f"📊 Storage: Google Sheets")
    print(f"🌐 Port: {port}")
    print(f"💡 Scripts based on what speaker actually says in video!\n")
    app.run(host='0.0.0.0', port=port, debug=False)
