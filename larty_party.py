import html
import json
import re
import os
import requests
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

session = requests.Session()

BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:151.0) Gecko/20100101 Firefox/151.0",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://larty.party",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}


def bootstrap_session():
    try:
        session.get("https://larty.party/board", headers=BASE_HEADERS, timeout=15)
    except Exception as e:
        print(f"Session bootstrap error: {e}")


# Initialize session on WSGI load for PythonAnywhere
bootstrap_session()


def fetch_url(url, referer="https://larty.party/board"):
    headers = {**BASE_HEADERS, "Referer": referer}
    try:
        res = session.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            return res.json()
        return None
    except Exception as e:
        print(f"Error fetching URL {url}: {e}")
        return None


def format_html_text(text):
    if not text:
        return ""

    # 1. Normalize line breaks: convert pre-rendered <br> tags to standard newlines
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)

    # 2. Extract and preserve styled spans (e.g. glowing text) to avoid stripping them
    spans = []

    def save_span(match):
        spans.append(match.group(0))
        return f"___PRESERVED_SPAN_{len(spans)-1}___"

    text = re.sub(
        r'<span\s+style="[^"]*"\s*>.*?</span>',
        save_span,
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # 3. Strip other pre-rendered raw HTML tags (e.g., raw <a> tags)
    text = re.sub(r"<[^>]+>", "", text)

    # 4. Unescape HTML entities (&gt; -> >, &lt; -> <, &quot; -> ", etc.)
    text = html.unescape(text)

    # 5. Clean up Windows carriage returns (\r\n -> \n)
    text = text.replace("\r", "")

    lines = text.split("\n")
    processed_lines = []

    for line in lines:
        stripped = line.strip()

        # Format >>12345 post reference links FIRST on pure text
        line_formatted = re.sub(
            r">>(\d+)",
            r'<a href="#post-\1" class="post-ref-link" onclick="scrollToPost(\1, event)">&gt;&gt;\1</a>',
            line,
        )

        # Classify prefixes on raw characters BEFORE applying HTML wrapper tags
        if stripped.startswith(">>"):
            processed_lines.append(line_formatted)
        elif stripped.startswith(">"):
            processed_lines.append(f'<span class="greentext">{line_formatted}</span>')
        elif stripped.startswith("<"):
            processed_lines.append(f'<span class="ambertext">{line_formatted}</span>')
        elif stripped.startswith("^"):
            processed_lines.append(f'<span class="bluetext">{line_formatted}</span>')
        else:
            processed_lines.append(line_formatted)

    text = "<br>".join(processed_lines)

    # Inline text formatting
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__([^_]+)__", r"<u>\1</u>", text)
    text = re.sub(r"~~([^~]+)~~", r"<s>\1</s>", text)
    text = re.sub(r"\|\|([^|]+)\|\|", r'<span class="spoiler">\1</span>', text)
    text = re.sub(r"~([^~]+)~", r'<span class="rainbow">\1</span>', text)

    # Markdown shortcode for custom glowing text: ++text++
    text = re.sub(
        r"\+\+([^+]+)\+\+",
        r'<span class="glow-text">\1</span>',
        text,
    )

    # Convert raw URLs into clickable dark grey links (excluding URLs inside existing HTML tags)
    text = re.sub(
        r"(?i)\b(https?://[^\s<]+)(?![^<]*>)",
        r'<a href="\1" target="_blank" rel="noopener noreferrer" class="dark-grey-link">\1</a>',
        text,
    )

    # Replace keywords safely outside existing HTML tags
    text = re.sub(
        r"(?i)\bsupersage\b(?![^<]*>)",
        r'<span class="supersagetext">supersage</span>',
        text,
    )
    text = re.sub(
        r"(?i)\bsage\b(?![^<]*>)", r'<span class="sagetext">sage</span>', text
    )

    # Restore preserved styled spans
    for i, original_span in enumerate(spans):
        text = text.replace(f"___PRESERVED_SPAN_{i}___", original_span)

    return text


def process_post(post, reactions_map=None):
    if reactions_map is None:
        reactions_map = {}

    post_id = post.get("id")
    text_content = post.get("content") or post.get("text") or ""

    post_reactions = (
        reactions_map.get(str(post_id)) or reactions_map.get(post_id) or {}
    )

    return {
        "id": post_id if post_id is not None else "N/A",
        "author": post.get("nickname")
        or post.get("anon_name")
        or post.get("username_archive")
        or "Anonymous",
        "title": format_html_text(post.get("title", "")),
        "content": format_html_text(text_content),
        "reply_count": post.get("reply_count", 0),
        "tags": post.get("tags", ""),
        "media": post.get("image_path", ""),
        "video": post.get("video_path", ""),
        "reactions": post_reactions,
    }


@app.route("/api/threads")
def get_threads():
    offset = request.args.get("offset", default=0, type=int)
    url = f"https://larty.party/api/board/threads?offset={offset}"
    data = fetch_url(url)

    if not data:
        return jsonify({"success": False, "nodes": []})

    nodes = data if isinstance(data, list) else data.get("threads", [])
    reactions_map = data.get("reactions", {}) if isinstance(data, dict) else {}

    formatted_nodes = []
    for thread in nodes:
        formatted_thread = process_post(thread, reactions_map)
        formatted_thread["preview_replies"] = [
            process_post(rep, reactions_map)
            for rep in thread.get("preview_replies", [])
        ]
        formatted_nodes.append(formatted_thread)

    return jsonify({"success": True, "nodes": formatted_nodes})


@app.route("/api/thread/<int:thread_id>")
def get_single_thread(thread_id):
    url = f"https://larty.party/api/board/thread/{thread_id}"
    data = fetch_url(url, referer=f"https://larty.party/thread/{thread_id}")

    if not data:
        return jsonify({"success": False, "error": "Thread not found"})

    raw_thread = data.get("thread", data) if isinstance(data, dict) else data
    raw_replies = data.get("replies", []) if isinstance(data, dict) else []
    reactions_map = data.get("reactions", {}) if isinstance(data, dict) else {}

    main_thread = process_post(raw_thread, reactions_map)
    main_thread["replies"] = [process_post(rep, reactions_map) for rep in raw_replies]

    return jsonify({"success": True, "thread": main_thread})


@app.route("/api/pow-challenge")
def get_pow_challenge():
    thread_id = request.args.get("thread_id", "")
    url = "https://larty.party/api/auth/pow-challenge?anon=1"
    headers = {
        **BASE_HEADERS,
        "Referer": (
            f"https://larty.party/thread/{thread_id}"
            if thread_id
            else "https://larty.party/board"
        ),
    }
    try:
        res = session.get(url, headers=headers, timeout=15)
        return jsonify({"success": True, "data": res.json()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/reply", methods=["POST"])
def post_reply():
    url = "https://larty.party/api/board/reply"
    form_data = request.form.to_dict()
    thread_id = form_data.get("thread_id", "")

    headers = {
        **BASE_HEADERS,
        "Referer": f"https://larty.party/thread/{thread_id}",
    }

    csrf_token = session.cookies.get("csrf_token")
    if csrf_token:
        headers["X-CSRF-Token"] = csrf_token

    try:
        res = session.post(url, data=form_data, headers=headers, timeout=15)
        updated_csrf = session.cookies.get("csrf_token")

        return (
            jsonify(
                {
                    "status": res.status_code,
                    "body": res.text,
                    "csrf_token": updated_csrf,
                }
            ),
            res.status_code,
        )
    except Exception as e:
        return jsonify({"status": 500, "error": str(e)}), 500


@app.route("/api/new-thread", methods=["POST"])
def post_thread():
    url = "https://larty.party/api/board/new-thread"
    form_data = request.form.to_dict()
    headers = {**BASE_HEADERS, "Referer": "https://larty.party/board"}
    csrf_token = session.cookies.get("csrf_token")
    if csrf_token:
        headers["X-CSRF-Token"] = csrf_token
    try:
        res = session.post(url, data=form_data, headers=headers, timeout=15)
        updated_csrf = session.cookies.get("csrf_token")
        return jsonify({"status": res.status_code, "body": res.text, "csrf_token": updated_csrf}), res.status_code
    except Exception as e:
        return jsonify({"status": 500, "error": str(e)}), 500


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Larty Board Viewer</title>
    <link rel="icon" type="image/png" href="https://lartywiki.ct.ws/images/c/c9/Logo.png">
    <style>
        * {
            box-sizing: border-box;
            border-radius: 0 !important;
            font-weight: normal !important;
        }

        body {
            background-color: #000000;
            color: #000000;
            font-family: Arial, sans-serif;
            margin: 20px;
        }
        .container { max-width: 900px; margin: 0 auto; }
        .nav-bar { margin-bottom: 15px; display: flex; align-items: center; justify-content: center; }
        
        h1 {
            color: #facc15;
            font-size: 1.8rem;
        }

        .banner-container {
            text-align: center;
            margin-bottom: 15px;
        }
        .board-banner {
            max-width: 100%;
            height: auto;
            max-height: 100px;
            border: 1px solid #ca8a04;
            display: inline-block;
        }

        .back-btn-container {
            text-align: center;
            margin-bottom: 20px;
        }

        .post-id-link {
            color: #854d0e;
            text-decoration: underline;
            cursor: pointer;
        }
        .post-id-link:hover { color: #000000; }
        
        .post-ref-link {
            color: #15803d !important;
            text-decoration: underline;
            cursor: pointer;
        }
        .post-ref-link:hover {
            color: #166534 !important;
        }

        .dark-grey-link {
            color: #374151 !important;
            text-decoration: underline !important;
            word-break: break-all;
        }
        .dark-grey-link:hover {
            color: #111827 !important;
        }

        .reply-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }

        .reply-btn {
            color: #854d0e;
            font-size: 0.85rem;
            text-decoration: underline;
            cursor: pointer;
            user-select: none;
        }

        .reply-btn:hover {
            color: #000000;
        }

        .thread {
            background-color: #facc15;
            border: 1px solid #ca8a04;
            padding: 15px;
            margin-bottom: 20px;
            color: #000000;
        }
        .meta { color: #713f12; font-size: 0.9em; margin-bottom: 10px; }
        .title { 
            color: #000000; 
            font-size: 1.2em; 
            margin-bottom: 10px; 
            cursor: pointer;
            border-bottom: 1px dashed #ca8a04;
            padding-bottom: 4px;
        }
        .content { margin-bottom: 15px; white-space: pre-wrap; word-break: break-word; color: #000000; }
        .media { 
            max-width: 300px; 
            max-height: 300px; 
            display: block; 
            margin-bottom: 10px; 
            border: 1px dashed #ca8a04; 
            background-color: #000000;
        }
        
        .greentext { color: #15803d !important; }
        .ambertext { color: #c2410c !important; }
        .bluetext { color: #1d4ed8 !important; }
        .rainbow { color: #b45309 !important; }
        .supersagetext { color: #dc2626 !important; font-weight: bold !important; }
        .sagetext { color: #6b7280 !important; font-weight: bold !important; }
        .glow-text {
            color: #39ff14 !important;
            text-shadow: 0 0 5px #39ff14, 0 0 9px #39ff14;
        }
        
        .spoiler { background-color: #000000; color: #000000; cursor: pointer; }
        .spoiler:hover { color: #ffffff; }

        .reactions-container {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin-top: 10px;
            margin-bottom: 5px;
        }
        .reaction-pill {
            background-color: #fef08a;
            border: 1px solid #ca8a04;
            padding: 2px 8px;
            font-size: 0.85em;
            display: inline-flex;
            align-items: center;
            gap: 4px;
            color: #713f12;
            cursor: default;
        }
        .reaction-pill:hover {
            border-color: #a16207;
            background-color: #fde047;
        }

        .replies {
            margin-left: 20px;
            border-left: 2px solid #ca8a04;
            padding-left: 10px;
        }

        .reply {
            background: #fde047;
            border: 1px solid #ca8a04;
            padding: 10px;
            margin-top: 8px;
            color: #000000;
            transition: background-color 0.3s ease;
        }
        
        .reply-form {
            background: #fde047;
            border: 1px solid #ca8a04;
            padding: 15px;
            margin-bottom: 20px;
            color: #000000;
        }
        .reply-form h3 {
            color: #713f12;
            margin-bottom: 10px;
        }
        .reply-form input[type="text"], .reply-form textarea {
            width: 100%;
            padding: 8px;
            margin-bottom: 10px;
            background: #fef08a;
            border: 1px solid #ca8a04;
            color: #000000;
            font-family: Arial, sans-serif;
            outline: none;
        }
        .reply-form input[type="text"]:focus, .reply-form textarea:focus {
            border-color: #854d0e;
        }
        .reply-form textarea { height: 80px; resize: vertical; }

        .post-controls { text-align: center; margin: 0 0 20px 0; }
        .post-form { background: #fde047; border: 1px solid #ca8a04; padding: 15px; margin-bottom: 20px; color: #000000; }
        .post-form h3 { color: #713f12; margin-bottom: 10px; }
        .post-form input[type="text"], .post-form textarea { width: 100%; padding: 8px; margin-bottom: 10px; background: #fef08a; border: 1px solid #ca8a04; color: #000000; font-family: Arial, sans-serif; outline: none; }
        .post-form input[type="text"]:focus, .post-form textarea:focus { border-color: #854d0e; }
        .post-form textarea { height: 120px; resize: vertical; }

        .tag-limit-msg {
            color: #713f12;
            font-size: 0.9em;
            margin-bottom: 8px;
        }

        .tag-picker {
            display: grid;
            grid-template-columns: repeat(6, 1fr);
            gap: 8px;
            margin-bottom: 12px;
        }

        .tag-option {
            background-color: #fef08a;
            color: #713f12;
            border: 1px solid #ca8a04;
            padding: 6px 4px;
            font-size: 0.85rem;
            text-align: center;
            cursor: pointer;
            transition: background-color 0.2s, color 0.2s, border-color 0.2s;
            width: 100%;
        }

        .tag-option:hover:not(.disabled) {
            background-color: #fde047;
        }

        .tag-option.selected {
            background-color: #ca8a04 !important;
            color: #ffffff !important;
            border-color: #854d0e !important;
            font-weight: bold !important;
        }

        .tag-option.disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .controls { text-align: center; margin: 20px 0; }
        button {
            background-color: #facc15;
            color: #000000;
            border: 1px solid #ca8a04;
            padding: 8px 20px;
            cursor: pointer;
            font-family: Arial, sans-serif;
            transition: background-color 0.2s;
        }
        button:hover { background-color: #fde047; }
        button:disabled { background-color: #333333; border-color: #555; color: #888; cursor: not-allowed; }
        .back-btn { display: none; }
        .status-msg { margin-top: 10px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="nav-bar">
            <h1 id="page-title" style="margin: 0;">BEST LARTTY CLIENT EVERRR</h1>
        </div>

        <div class="banner-container">
            <img id="board-banner" class="board-banner" src="" alt="Larty Board Banner" />
        </div>

        <div class="back-btn-container">
            <button id="back-btn" class="back-btn" onclick="showBoardIndex()">Return</button>
        </div>
        
        <div id="post-form-container" class="post-form">
            <input type="text" id="post-title" placeholder="Subject" />
            <textarea id="post-content" placeholder="Description here..."></textarea>
            <div class="tag-limit-msg">Select up to 4 tags.</div>
            <div class="tag-picker" id="tag-picker"></div>
            <input type="text" id="post-name" placeholder="Name (Default: Anonymous)" value="" />
            <button id="post-submit-btn" onclick="submitThread()">Post</button>
            <div id="post-status" class="status-msg"></div>
        </div>

        <div id="threads-container"></div>
        
        <div class="controls" id="controls">
            <button id="load-more-btn" onclick="loadThreads()">Load Next Offset</button>
        </div>
    </div>

    <script>
        let currentOffset = 0;
        let isSingleThreadView = false;

        function refreshBanner() {
            const bannerEl = document.getElementById('board-banner');
            if (bannerEl) {
                bannerEl.src = `https://larty.party/banner.img?_t=${new Date().getTime()}`;
            }
        }

        function scrollToPost(postId, event) {
            if (event) event.preventDefault();
            const targetEl = document.getElementById(`post-${postId}`);
            if (targetEl) {
                targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
                const originalBg = targetEl.style.backgroundColor;
                targetEl.style.backgroundColor = '#fef08a';
                setTimeout(() => {
                    targetEl.style.backgroundColor = originalBg;
                }, 1000);
            }
        }

        function insertReplyRef(postId) {
            const textarea = document.getElementById('reply-content');
            if (!textarea) return;
            const refText = `>>${postId}\\n`;
            if (textarea.value && !textarea.value.endsWith('\\n')) {
                textarea.value += '\\n' + refText;
            } else {
                textarea.value += refText;
            }
            textarea.focus();
        }

        function renderMedia(mediaPath, videoPath) {
            if (videoPath) {
                return `<video class="media" controls><source src="https://larty.party/${videoPath}"></video>`;
            }
            if (mediaPath) {
                return `<img class="media" src="https://larty.party/${mediaPath}" />`;
            }
            return '';
        }

        function renderReactions(reactions) {
            if (!reactions || Object.keys(reactions).length === 0) return '';
            
            let html = '<div class="reactions-container">';
            for (const [emoji, details] of Object.entries(reactions)) {
                const count = details.c || 0;
                const users = details.u || '';
                html += `
                    <div class="reaction-pill" title="By: ${users}">
                        <span>${emoji}</span>
                        <span>${count}</span>
                    </div>`;
            }
            html += '</div>';
            return html;
        }

        async function sha256(message) {
            const msgBuffer = new TextEncoder().encode(message);
            const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
            const hashArray = Array.from(new Uint8Array(hashBuffer));
            return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
        }

        async function solvePoW(challengeStr, difficulty) {
            const targetPrefix = '0'.repeat(difficulty);
            let nonce = 0;
            while (true) {
                const nonceHex = nonce.toString(16);
                const hash = await sha256(challengeStr + nonceHex);
                if (hash.startsWith(targetPrefix)) {
                    return nonceHex;
                }
                nonce++;
                if (nonce % 5000 === 0) {
                    await new Promise(r => setTimeout(r, 0));
                }
            }
        }

        async function submitReply(threadId) {
            const content = document.getElementById('reply-content').value.trim();
            const anonName = document.getElementById('reply-name').value.trim() || 'Anonymous';
            const statusEl = document.getElementById('reply-status');
            const submitBtn = document.getElementById('reply-submit-btn');

            if (!content) {
                statusEl.innerText = 'Content cannot be empty.';
                statusEl.style.color = '#dc2626';
                return;
            }

            submitBtn.disabled = true;
            statusEl.style.color = '#713f12';
            
            try {
                statusEl.innerText = 'Initiating post request...';
                let formData = new FormData();
                formData.append('thread_id', threadId);
                formData.append('content', content);
                formData.append('is_anon', '1');
                formData.append('anon_name', anonName);

                let response = await fetch('/api/reply', { method: 'POST', body: formData });
                let result = await response.json();

                if (result.status === 428) {
                    statusEl.innerText = 'Challenge required. Fetching PoW params...';
                    
                    const powRes = await fetch(`/api/pow-challenge?thread_id=${threadId}`);
                    const powData = await powRes.json();

                    if (!powData.success) {
                        throw new Error('Failed to retrieve PoW challenge');
                    }

                    const challenge = powData.data.challenge;
                    const difficulty = powData.data.difficulty || 4;

                    statusEl.innerText = `Solving PoW (Difficulty: ${difficulty})...`;
                    const nonce = await solvePoW(challenge, difficulty);

                    statusEl.innerText = 'PoW solved! Submitting final payload...';
                    formData.append('pow_challenge', challenge);
                    formData.append('pow_nonce', nonce);

                    response = await fetch('/api/reply', { method: 'POST', body: formData });
                    result = await response.json();
                }

                if (result.status === 200) {
                    statusEl.innerText = 'Reply posted successfully!';
                    statusEl.style.color = '#15803d';
                    document.getElementById('reply-content').value = '';
                    
                    setTimeout(() => openThread(threadId), 1000);
                } else {
                    statusEl.innerText = `Error posting reply (HTTP ${result.status})`;
                    statusEl.style.color = '#dc2626';
                }
            } catch (err) {
                console.error(err);
                statusEl.innerText = 'Error submitting reply.';
                statusEl.style.color = '#dc2626';
            } finally {
                submitBtn.disabled = false;
            }
        }

        const POST_TAGS = [
            'Agora', 'Anime', 'Art', 'Crypto', 'Culture', 'Cypher',
            'Defense', 'Fit', 'Funny', 'Gaming', 'General', 'Giga',
            'Int', 'Literature', 'Media', 'Meta', 'Misc', 'Politics',
            'Music', 'Raid', 'Religion', 'Schizo', 'Theory'
        ];

        let selectedPostTags = [];

        function initTagPicker() {
            const picker = document.getElementById('tag-picker');
            if (!picker) return;

            picker.innerHTML = '';
            POST_TAGS.forEach(tag => {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'tag-option';
                button.innerText = tag;
                button.setAttribute('aria-pressed', 'false');
                button.onclick = () => togglePostTag(tag, button);
                picker.appendChild(button);
            });
        }

        function togglePostTag(tag, button) {
            if (selectedPostTags.includes(tag)) {
                selectedPostTags = selectedPostTags.filter(t => t !== tag);
            } else {
                if (selectedPostTags.length >= 4) {
                    document.querySelector('.tag-limit-msg').innerText = 'Maximum 4 tags.';
                    return;
                }
                selectedPostTags.push(tag);
            }

            document.querySelectorAll('.tag-option').forEach(option => {
                const isSelected = selectedPostTags.includes(option.innerText);
                option.classList.toggle('selected', isSelected);
                option.classList.toggle(
                    'disabled',
                    selectedPostTags.length >= 4 && !isSelected
                );
                option.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
            });

            document.querySelector('.tag-limit-msg').innerText =
                `${selectedPostTags.length}/4 tags selected.`;
        }

        function togglePostForm() {
            const form = document.getElementById('post-form-container');
            const button = document.getElementById('post-toggle-btn');
            const isHidden = form.style.display === 'none';
            form.style.display = isHidden ? 'block' : 'none';
            button.innerText = isHidden ? 'Close Post' : 'Post';
            if (isHidden) document.getElementById('post-title').focus();
        }

        async function submitThread() {
            const title = document.getElementById('post-title').value.trim();
            const content = document.getElementById('post-content').value.trim();
            const tags = selectedPostTags.join(',');
            const anonName = document.getElementById('post-name').value.trim() || 'Anonymous';
            const statusEl = document.getElementById('post-status');
            const submitBtn = document.getElementById('post-submit-btn');
            if (!title) { statusEl.innerText = 'Title cannot be empty.'; statusEl.style.color = '#dc2626'; return; }
            if (!content) { statusEl.innerText = 'Content cannot be empty.'; statusEl.style.color = '#dc2626'; return; }
            submitBtn.disabled = true; statusEl.style.color = '#713f12';
            try {
                statusEl.innerText = 'Initiating post request...';
                let formData = new FormData();
                formData.append('title', title); formData.append('content', content);
                formData.append('tags', tags); formData.append('is_anon', '1'); formData.append('anon_name', anonName);
                let response = await fetch('/api/new-thread', { method: 'POST', body: formData });
                let result = await response.json();
                if (result.status === 428) {
                    statusEl.innerText = 'Challenge required. Fetching PoW params...';
                    const powRes = await fetch('/api/pow-challenge');
                    const powData = await powRes.json();
                    if (!powData.success) throw new Error('Failed to retrieve PoW challenge');
                    const challenge = powData.data.challenge;
                    const difficulty = powData.data.difficulty || 4;
                    statusEl.innerText = `Solving PoW (Difficulty: ${difficulty})...`;
                    const nonce = await solvePow(challenge, difficulty);
                    statusEl.innerText = 'PoW solved! Submitting final payload...';
                    formData.append('pow_challenge', challenge); formData.append('pow_nonce', nonce);
                    response = await fetch('/api/new-thread', { method: 'POST', body: formData });
                    result = await response.json();
                }
                if (result.status === 200) {
                    statusEl.innerText = 'Thread posted successfully!'; statusEl.style.color = '#15803d';
                    document.getElementById('post-title').value = ''; document.getElementById('post-content').value = '';
                    setTimeout(() => {
                        document.getElementById('post-form-container').style.display = 'none';
                        document.getElementById('post-toggle-btn').innerText = 'Post';
                        document.getElementById('threads-container').innerHTML = '';
                        currentOffset = 0;
                        const loadMoreBtn = document.getElementById('load-more-btn');
                        loadMoreBtn.disabled = false; loadMoreBtn.innerText = 'Load Next Offset';
                        loadThreads();
                    }, 500);
                } else { statusEl.innerText = `Error posting thread (HTTP ${result.status})`; statusEl.style.color = '#dc2626'; }
            } catch (err) { console.error(err); statusEl.innerText = 'Error submitting thread.'; statusEl.style.color = '#dc2626'; }
            finally { submitBtn.disabled = false; }
        }

        async function openThread(threadId) {
            const container = document.getElementById('threads-container');
            const controls = document.getElementById('controls');
            const backBtn = document.getElementById('back-btn');
            const postForm = document.getElementById('post-form-container');
            
            container.innerHTML = '<p style="color: #ffffff;">Loading thread...</p>';
            controls.style.display = 'none';
            postForm.style.display = 'none';
            backBtn.style.display = 'inline-block';
            isSingleThreadView = true;

            try {
                const response = await fetch(`/api/thread/${threadId}`);
                const data = await response.json();

                if (data.success && data.thread) {
                    const thread = data.thread;
                    
                    let repliesHtml = '';
                    if (thread.replies && thread.replies.length > 0) {
                        repliesHtml = '<div class="replies">';
                        thread.replies.forEach(rep => {
                            repliesHtml += `
                                <div class="reply" id="post-${rep.id}">
                                    <div class="reply-header">
                                        <div class="meta" style="margin-bottom: 0;">[<span class="post-id-link" onclick="scrollToPost(${rep.id})">No.${rep.id}</span>] -- Author: ${rep.author}</div>
                                        <span class="reply-btn" onclick="insertReplyRef(${rep.id})">[Reply]</span>
                                    </div>
                                    ${renderMedia(rep.media, rep.video)}
                                    <div class="content">${rep.content}</div>
                                    ${renderReactions(rep.reactions)}
                                </div>`;
                        });
                        repliesHtml += '</div>';
                    }

                    const replyFormHtml = `
                        <div class="reply-form">
                            <input type="text" id="reply-name" placeholder="Name (Default: Anonymous)" value="" />
                            <textarea id="reply-content" placeholder="Comment here..."></textarea>
                            <button id="reply-submit-btn" onclick="submitReply(${thread.id})">Post</button>
                            <div id="reply-status" class="status-msg"></div>
                        </div>
                    `;

                    container.innerHTML = `
                        ${replyFormHtml}
                        <div class="thread" id="post-${thread.id}">
                            <div class="reply-header">
                                <div class="meta" style="margin-bottom: 0;">
                                    [<span class="post-id-link">No.${thread.id}</span>] -- Author: ${thread.author} -- Replies: ${thread.reply_count}
                                </div>
                                <span class="reply-btn" onclick="insertReplyRef(${thread.id})">[Reply]</span>
                            </div>
                            ${thread.title ? `<div class="title">${thread.title}</div>` : ''}
                            ${renderMedia(thread.media, thread.video)}
                            <div class="content">${thread.content}</div>
                            ${renderReactions(thread.reactions)}
                            <h3 style="color: #713f12; margin-top: 15px;">Replies (${thread.replies ? thread.replies.length : 0})</h3>
                            ${repliesHtml}
                        </div>
                    `;
                } else {
                    container.innerHTML = '<p style="color: #ffffff;">Failed to load thread details.</p>';
                }
            } catch (err) {
                console.error(err);
                container.innerHTML = '<p style="color: #ffffff;">Error connecting to thread endpoint.</p>';
            }
        }

        function showBoardIndex() {
            document.getElementById('back-btn').style.display = 'none';
            document.getElementById('post-form-container').style.display = 'block';
            document.getElementById('controls').style.display = 'block';
            document.getElementById('threads-container').innerHTML = '';
            currentOffset = 0;
            isSingleThreadView = false;
            refreshBanner();
            loadThreads();
        }

        async function loadThreads() {
            if (isSingleThreadView) return;

            const btn = document.getElementById('load-more-btn');
            btn.disabled = true;
            btn.innerText = 'Loading...';

            try {
                const response = await fetch(`/api/threads?offset=${currentOffset}`);
                const data = await response.json();

                if (data.success && data.nodes.length > 0) {
                    const container = document.getElementById('threads-container');
                    
                    data.nodes.forEach(thread => {
                        const threadEl = document.createElement('div');
                        threadEl.className = 'thread';
                        threadEl.id = `post-${thread.id}`;
                        
                        let previewRepliesHtml = '';
                        if (thread.preview_replies && thread.preview_replies.length > 0) {
                            previewRepliesHtml = '<div class="replies">';
                            thread.preview_replies.forEach(rep => {
                                previewRepliesHtml += `
                                    <div class="reply" id="post-${rep.id}">
                                        <strong>[No.${rep.id}]</strong>: ${rep.content}
                                        ${renderReactions(rep.reactions)}
                                    </div>`;
                            });
                            previewRepliesHtml += '</div>';
                        }

                        threadEl.innerHTML = `
                            <div class="meta">
                                [<span class="post-id-link" onclick="openThread(${thread.id})">No.${thread.id}</span>] 
                                -- Author: ${thread.author} -- Replies: ${thread.reply_count}
                            </div>
                            ${thread.title ? `<div class="title" onclick="openThread(${thread.id})">${thread.title}</div>` : ''}
                            ${renderMedia(thread.media, thread.video)}
                            <div class="content">${thread.content}</div>
                            ${renderReactions(thread.reactions)}
                            ${previewRepliesHtml}
                        `;
                        container.appendChild(threadEl);
                    });

                    currentOffset += 50;
                    btn.disabled = false;
                    btn.innerText = 'Load Next Offset';
                } else {
                    btn.innerText = 'No More Threads';
                }
            } catch (err) {
                console.error(err);
                btn.innerText = 'Error Loading Threads';
            }
        }

        refreshBanner();
        initTagPicker();
        loadThreads();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
