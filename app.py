from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import requests
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


def create_instagram_scripts(video_summaries, num_scripts):
    """Generate viral Instagram scripts using Perplexity"""
    try:
        combined = "\n\n".join([
            f"VIDEO {i+1} ({v['title']}):\n{v['transcript'][:3000]}" 
            for i, v in enumerate(video_summaries)
        ])
        
        prompt = f"""You are India's top viral Instagram Reels scriptwriter for Hindi news content.

Create {num_scripts} different Instagram Reels scripts based ONLY on the video content below.

VIDEO TRANSCRIPTS:
{combined[:10000]}

CRITICAL RULES:
- Use ONLY information from the transcripts above
- DO NOT add external news or web search results
- Extract the ACTUAL topics discussed in the videos
- If video discusses one main topic, break it into subtopics

═══════════════════════════════════════════════════════════
SCRIPT FORMAT (CONTINUOUS MONOLOGUE):
═══════════════════════════════════════════════════════════

1. Write as ONE continuous monologue - NOT bullets, NOT numbered lists
2. Do NOT use "Story 1", "Story 2" labels
3. Do NOT include citations [1], [2], [3]
4. Do NOT use section labels like "Hook:", "Opening:"
5. Write pure spoken text that flows naturally

LENGTH: 450-550 words per script (MANDATORY)

TONE: Young, energetic news influencer
- Use: "dosto", "bhai log", "suno yaar", "dekho", "arrey"
- Mix emotions: shock, anger, concern, hope
- Sound passionate and authentic

COVERAGE: Extract 7-9 key points from video content
TRANSITIONS: "Aur sunao...", "Lekin baat yahin nahi rukti...", "Ab samjho..."
EMOJIS: Use naturally (🔥😤💪🎯🚨) but sparingly

STRUCTURE:
- Opening hook (20-30 words) based on video's main topic
- Main body (370-450 words) flowing through main points
- Closing CTA (30-40 words)

OUTPUT FORMAT:

═══════════════════════
SCRIPT [NUMBER]
═══════════════════════
TITLE: [Catchy Hinglish title]
THEME: [Main subject]
WORD COUNT: [Count]

[CONTINUOUS SCRIPT CONTENT]

═══════════════════════

Generate {num_scripts} unique scripts NOW."""

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
            clean = re.sub(r'\[\d+\]', '', clean)  # Remove citations
            
            scripts.append({
                'number': int(script_num),
                'title': title,
                'theme': theme,
                'content': clean,
                'word_count': len(clean.split())
            })
    
    return scripts[:num_scripts]


def upload_to_sheets(scripts, video_count):
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
                'Script Content', 'Word Count', 'Videos Processed', 'Status'
            ]
            worksheet.update('A1:H1', [headers])
            worksheet.format('A1:H1', {
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
                s['content'], s['word_count'], video_count, 'Ready for Use'
            ])
        
        if rows:
            worksheet.update(f'A{next_row}', rows)
            worksheet.columns_auto_resize(0, 8)
        
        print(f"   ✅ Uploaded {len(scripts)} scripts to Google Sheets")
        return spreadsheet.url
        
    except Exception as e:
        raise Exception(f"Sheet upload error: {str(e)}")


# ========== API ENDPOINTS ==========

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        'status': 'online',
        'service': 'Instagram Reels Script Generator API',
        'version': '10.0.0 - Next.js Integration',
        'endpoints': {
            'POST /generate': 'Generate scripts from video transcripts'
        }
    }), 200


@app.route('/generate', methods=['POST'])
def generate_scripts():
    """Generate scripts from transcripts"""
    
    try:
        if not PERPLEXITY_API_KEY:
            return jsonify({
                'status': 'error',
                'message': 'PERPLEXITY_API_KEY not configured'
            }), 500
        
        data = request.get_json()
        
        videos = data.get('videos', [])
        num_scripts = data.get('num_scripts', 2)
        
        if not videos or len(videos) == 0:
            return jsonify({
                'status': 'error',
                'message': 'Please provide at least 1 video with transcript'
            }), 400
        
        print(f"\n{'='*60}")
        print(f"📥 NEW REQUEST: {len(videos)} videos, {num_scripts} scripts")
        print(f"{'='*60}\n")
        
        # Generate scripts
        print(f"🎬 Generating {num_scripts} viral scripts...")
        raw_scripts = create_instagram_scripts(videos, num_scripts)
        parsed = parse_scripts(raw_scripts, num_scripts)
        
        print(f"\n✅ Generated {len(parsed)} scripts:")
        for s in parsed:
            print(f"   Script {s['number']}: {s['word_count']} words - {s['title']}")
        
        print(f"\n📤 Uploading to Google Sheets...")
        sheet_url = upload_to_sheets(parsed, len(videos))
        
        print(f"✅ Uploaded to: {sheet_url}")
        print(f"\n{'='*60}")
        print(f"🎉 REQUEST COMPLETED!")
        print(f"{'='*60}\n")
        
        return jsonify({
            'status': 'success',
            'message': 'Scripts generated successfully!',
            'data': {
                'videos_processed': len(videos),
                'scripts_generated': len(parsed),
                'sheet_url': sheet_url,
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
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


if __name__ == '__main__':
    port = int(os.getenv('PORT', 7860))
    print(f"\n🚀 Starting Script Generator...")
    print(f"🎬 Receives transcripts from Next.js")
    print(f"🤖 Generates scripts with Perplexity")
    print(f"📊 Uploads to Google Sheets")
    print(f"🌐 Port: {port}\n")
    app.run(host='0.0.0.0', port=port, debug=False)
