import hashlib
import json
import os
import sqlite3
import csv
import subprocess
import tempfile
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from threading import Thread

from flask import Flask, g, jsonify, render_template, request, send_file

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "english.db"
DIALOGUES_PATH = DATA_DIR / "dialogues.json"
TTS_CACHE_DIR = DATA_DIR / "tts_cache"
TTS_VOICE = "en-US-JennyNeural"
CST = timezone(timedelta(hours=8))

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "english-scenario-secret-2026")

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(str(DB_PATH))
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db


@app.teardown_appcontext
def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_PATH))
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_id TEXT NOT NULL,
            viewed_at TEXT NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_id TEXT NOT NULL UNIQUE,
            is_completed INTEGER DEFAULT 0,
            completed_at TEXT,
            last_studied TEXT
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_scenario ON activity(scenario_id)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_progress_scenario ON progress(scenario_id)"
    )
    db.commit()
    db.close()


def record_view(scenario_id):
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    db = get_db()
    db.execute(
        "INSERT INTO activity (scenario_id, viewed_at) VALUES (?, ?)",
        (scenario_id, now),
    )
    db.commit()


def get_progress(scenario_id):
    db = get_db()
    row = db.execute(
        "SELECT is_completed, completed_at, last_studied FROM progress WHERE scenario_id=?",
        (scenario_id,)
    ).fetchone()
    if row:
        return {
            "is_completed": bool(row["is_completed"]),
            "completed_at": row["completed_at"],
            "last_studied": row["last_studied"]
        }
    return {
        "is_completed": False,
        "completed_at": None,
        "last_studied": None
    }


def set_completed(scenario_id, completed):
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    db = get_db()
    
    row = db.execute(
        "SELECT id FROM progress WHERE scenario_id=?",
        (scenario_id,)
    ).fetchone()
    
    if row:
        db.execute(
            "UPDATE progress SET is_completed=?, completed_at=?, last_studied=? WHERE scenario_id=?",
            (1 if completed else 0, now if completed else None, now, scenario_id)
        )
    else:
        db.execute(
            "INSERT INTO progress (scenario_id, is_completed, completed_at, last_studied) VALUES (?, ?, ?, ?)",
            (scenario_id, 1 if completed else 0, now if completed else None, now)
        )
    
    if not completed:
        db.execute("DELETE FROM activity WHERE scenario_id=?", (scenario_id,))
    
    db.commit()
    
    return get_progress(scenario_id)


def checkin(scenario_id):
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    db = get_db()
    
    row = db.execute(
        "SELECT id, is_completed, completed_at FROM progress WHERE scenario_id=?",
        (scenario_id,)
    ).fetchone()
    
    if row:
        completed_at = row["completed_at"] if row["completed_at"] else now
        db.execute(
            "UPDATE progress SET is_completed=1, completed_at=?, last_studied=? WHERE scenario_id=?",
            (completed_at, now, scenario_id)
        )
    else:
        db.execute(
            "INSERT INTO progress (scenario_id, is_completed, completed_at, last_studied) VALUES (?, 1, ?, ?)",
            (scenario_id, now, now)
        )
    db.commit()
    
    return get_progress(scenario_id)


def load_dialogues():
    with open(DIALOGUES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Routes — pages
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Routes — API
# ---------------------------------------------------------------------------
@app.route("/api/categories")
def api_categories():
    """Get all categories with scenario overview and progress"""
    data = load_dialogues()
    db = get_db()
    
    rows = db.execute(
        "SELECT scenario_id, MAX(viewed_at) as viewed_at FROM activity GROUP BY scenario_id"
    ).fetchall()
    viewed = {r["scenario_id"]: r["viewed_at"] for r in rows}
    
    # Get progress
    progress_rows = db.execute(
        "SELECT scenario_id, is_completed, completed_at, last_studied FROM progress"
    ).fetchall()
    progress = {}
    for r in progress_rows:
        progress[r["scenario_id"]] = {
            "is_completed": bool(r["is_completed"]),
            "completed_at": r["completed_at"],
            "last_studied": r["last_studied"]
        }
    
    result = []
    for cat in data["categories"]:
        scenarios_out = []
        for s in cat["scenarios"]:
            prog = progress.get(s["id"], {})
            scenarios_out.append(
                {
                    "id": s["id"],
                    "title": s["title"],
                    "title_cn": s["title_cn"],
                    "difficulty": s["difficulty"],
                    "status": s["status"],
                    "viewed_at": viewed.get(s["id"]),
                    "is_completed": prog.get("is_completed", False),
                    "completed_at": prog.get("completed_at"),
                    "last_studied": prog.get("last_studied"),
                }
            )
        result.append({"id": cat["id"], "name": cat["name"], "scenarios": scenarios_out})
    return jsonify(result)


@app.route("/api/scenario/<scenario_id>")
def api_scenario(scenario_id):
    data = load_dialogues()
    for cat in data["categories"]:
        for s in cat["scenarios"]:
            if s["id"] == scenario_id:
                record_view(scenario_id)
                db = get_db()
                row = db.execute(
                    "SELECT MAX(viewed_at) as last_viewed FROM activity WHERE scenario_id=?",
                    (scenario_id,),
                ).fetchone()
                s["viewed_at"] = row["last_viewed"] if row else None

                # add hash for each line (for TTS caching)
                for line in s.get("lines", []):
                    line["hash"] = hashlib.sha256(
                        line["text"].encode()
                    ).hexdigest()[:12]

                return jsonify(s)
    return jsonify({"error": "not found"}), 404


@app.route("/api/review")
def api_review():
    data = load_dialogues()
    db = get_db()
    rows = db.execute(
        """
        SELECT scenario_id, MAX(viewed_at) as last_viewed, COUNT(*) as view_count
        FROM activity GROUP BY scenario_id ORDER BY last_viewed DESC LIMIT 50
        """
    ).fetchall()

    # build id -> scenario lookup
    lookup = {}
    for cat in data["categories"]:
        for s in cat["scenarios"]:
            lookup[s["id"]] = s

    result = []
    for r in rows:
        s = lookup.get(r["scenario_id"])
        if s and s["status"] == "ready":
            progress = get_progress(r["scenario_id"])
            result.append(
                {
                    "id": s["id"],
                    "title": s["title"],
                    "title_cn": s["title_cn"],
                    "difficulty": s["difficulty"],
                    "viewed_at": r["last_viewed"],
                    "view_count": r["view_count"],
                    "is_completed": progress["is_completed"],
                    "completed_at": progress["completed_at"],
                    "checkin_count": progress["checkin_count"],
                    "last_checkin": progress["last_checkin"],
                }
            )
    return jsonify(result)


# ---------------------------------------------------------------------------
# Learning Progress API
# ---------------------------------------------------------------------------
@app.route("/api/progress/<scenario_id>", methods=["GET"])
def api_progress_get(scenario_id):
    """Get learning progress for a scenario"""
    progress = get_progress(scenario_id)
    return jsonify(progress)


@app.route("/api/progress/<scenario_id>/complete", methods=["POST"])
def api_progress_complete(scenario_id):
    """Mark a scenario as completed or uncompleted"""
    body = request.get_json(silent=True) or {}
    completed = body.get("completed", True)
    
    progress = set_completed(scenario_id, completed)
    return jsonify(progress)


@app.route("/api/progress/<scenario_id>/checkin", methods=["POST"])
def api_progress_checkin(scenario_id):
    """Checkin for a scenario (mark as completed if not already)"""
    progress = checkin(scenario_id)
    return jsonify(progress)


# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------
def get_tts_audio(text):
    """Get TTS audio, using cache if available"""
    text = text.strip()
    if not text:
        return None, None
    h = hashlib.sha256(text.encode()).hexdigest()[:12]
    cache_path = TTS_CACHE_DIR / f"{h}.mp3"
    
    if cache_path.exists():
        return str(cache_path), h
    
    # generate with edge-tts (sync via subprocess — edge-tts is a CLI tool)
    try:
        import subprocess
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name

        result = subprocess.run(
            [
                "edge-tts",
                "--voice", TTS_VOICE,
                "--text", text,
                "--write-media", tmp_path,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )

        if result.returncode != 0:
            return None, None

        # move to cache
        import shutil
        shutil.move(tmp_path, str(cache_path))

        return str(cache_path), h
    except Exception:
        return None, None

@app.route("/api/tts", methods=["POST"])
def api_tts_post():
    body = request.get_json(silent=True) or {}
    text = body.get("text", "").strip()
    if not text:
        return jsonify({"error": "text required"}), 400
    
    audio_path, _ = get_tts_audio(text)
    if not audio_path:
        return jsonify({"error": "tts failed"}), 500
    
    response = send_file(audio_path, mimetype="audio/mpeg")
    response.headers["Cache-Control"] = "public, max-age=31536000"  # Cache 1 year
    return response

@app.route("/api/tts/<hash_str>", methods=["GET"])
def api_tts_get(hash_str):
    """Get TTS audio by hash (for browser caching)"""
    cache_path = TTS_CACHE_DIR / f"{hash_str}.mp3"
    if not cache_path.exists():
        return jsonify({"error": "not found"}), 404
    response = send_file(cache_path, mimetype="audio/mpeg")
    response.headers["Cache-Control"] = "public, max-age=31536000"
    return response

def get_slow_tts_audio(text):
    """Get slow-speed TTS audio (0.5x rate)"""
    text = text.strip()
    if not text:
        return None, None
    h = hashlib.sha256((text + "_slow").encode()).hexdigest()[:12]
    cache_path = TTS_CACHE_DIR / f"{h}.mp3"
    
    if cache_path.exists():
        return str(cache_path), h
    
    try:
        import subprocess
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name

        result = subprocess.run(
            [
                "edge-tts",
                "--voice", TTS_VOICE,
                "--text", text,
                "--write-media", tmp_path,
                "--rate=-50%",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )

        if result.returncode != 0:
            return None, None

        import shutil
        shutil.move(tmp_path, str(cache_path))

        return str(cache_path), h
    except Exception:
        return None, None

@app.route("/api/tts/slow", methods=["POST"])
def api_tts_slow():
    body = request.get_json(silent=True) or {}
    text = body.get("text", "").strip()
    if not text:
        return jsonify({"error": "text required"}), 400
    
    audio_path, h = get_slow_tts_audio(text)
    if not audio_path:
        return jsonify({"error": "tts failed"}), 500
    
    response = send_file(audio_path, mimetype="audio/mpeg")
    response.headers["Cache-Control"] = "public, max-age=31536000"
    return response


# ---------------------------------------------------------------------------
# CSV Import
# ---------------------------------------------------------------------------
@app.route("/api/import/csv", methods=["POST"])
def api_import_csv():
    """Import scenarios from CSV file"""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400
    
    try:
        reader = csv.DictReader(file.stream)
        
        # CSV format: id,title,title_cn,difficulty,characters,speaker,text,text_cn,answer
        # characters: comma-separated list like "Star,Alex"
        scenarios = {}
        
        for row in reader:
            sc_id = row.get("id", "").strip()
            if not sc_id:
                continue
            
            if sc_id not in scenarios:
                scenarios[sc_id] = {
                    "id": sc_id,
                    "title": row.get("title", "").strip(),
                    "title_cn": row.get("title_cn", "").strip(),
                    "difficulty": row.get("difficulty", "A2").strip(),
                    "characters": [c.strip() for c in row.get("characters", "Star").split(",")],
                    "status": "ready",
                    "lines": [],
                    "blanks": [],
                    "prev_id": None,
                    "next_id": None
                }
            
            speaker = row.get("speaker", "Star").strip()
            text = row.get("text", "").strip()
            text_cn = row.get("text_cn", "").strip()
            answer = row.get("answer", "").strip()
            
            if text:
                scenarios[sc_id]["lines"].append({
                    "speaker": speaker,
                    "text": text,
                    "text_cn": text_cn
                })
                
                if answer:
                    blank_text = text.replace(answer, "___")
                    scenarios[sc_id]["blanks"].append({
                        "speaker": speaker,
                        "text": blank_text,
                        "answer": answer
                    })
        
        # Load existing dialogues
        data = load_dialogues()
        
        # Update scenarios
        updated_count = 0
        for cat in data["categories"]:
            for s in cat["scenarios"]:
                if s["id"] in scenarios:
                    s.update(scenarios[s["id"]])
                    updated_count += 1
        
        # Save back
        with open(DIALOGUES_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # Pre-generate TTS audio in background
        Thread(target=pregenerate_all_audio, args=(list(scenarios.keys()),)).start()
        
        return jsonify({"success": True, "updated": updated_count})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/export/template", methods=["GET"])
def api_export_template():
    """Export CSV template for import"""
    template = [
        {"id": "scenario-id", "title": "English Title", "title_cn": "中文标题", "difficulty": "A2", "characters": "Star,Alex", "speaker": "Star", "text": "Your sentence here", "text_cn": "中文翻译", "answer": ""},
        {"id": "scenario-id", "title": "", "title_cn": "", "difficulty": "", "characters": "", "speaker": "Alex", "text": "Response sentence", "text_cn": "回应的中文翻译", "answer": "keyword"},
    ]
    
    import io
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["id", "title", "title_cn", "difficulty", "characters", "speaker", "text", "text_cn", "answer"])
    writer.writeheader()
    writer.writerows(template)
    
    response = send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype="text/csv",
        as_attachment=True,
        download_name="template.csv"
    )
    return response


# ---------------------------------------------------------------------------
# Audio Pre-generation
# ---------------------------------------------------------------------------
def pregenerate_audio(text):
    """Generate TTS audio and cache it"""
    text = text.strip()
    if not text:
        return False
    
    h = hashlib.sha256(text.encode()).hexdigest()[:12]
    cache_path = TTS_CACHE_DIR / f"{h}.mp3"
    
    if cache_path.exists():
        return True
    
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name
        
        result = subprocess.run(
            [
                "edge-tts",
                "--voice", TTS_VOICE,
                "--text", text,
                "--write-media", tmp_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        if result.returncode != 0:
            return False
        
        shutil.move(tmp_path, str(cache_path))
        return True
    except Exception:
        return False


def pregenerate_all_audio(scenario_ids=None):
    """Pre-generate TTS audio for all ready scenarios"""
    data = load_dialogues()
    generated = 0
    skipped = 0
    
    for cat in data["categories"]:
        for s in cat["scenarios"]:
            if scenario_ids and s["id"] not in scenario_ids:
                continue
            if s["status"] != "ready":
                continue
            
            for line in s.get("lines", []):
                text = line.get("text", "")
                if pregenerate_audio(text):
                    generated += 1
                else:
                    skipped += 1
    
    print(f"TTS pre-generation completed: {generated} generated, {skipped} skipped")
    return generated, skipped


@app.route("/api/pregenerate", methods=["POST"])
def api_pregenerate():
    """Trigger audio pre-generation"""
    body = request.get_json(silent=True) or {}
    scenario_ids = body.get("scenario_ids")
    
    if scenario_ids:
        Thread(target=pregenerate_all_audio, args=(scenario_ids,)).start()
        return jsonify({"status": "started", "target": "selected scenarios"})
    else:
        Thread(target=pregenerate_all_audio).start()
        return jsonify({"status": "started", "target": "all ready scenarios"})


@app.route("/api/audio/status", methods=["GET"])
def api_audio_status():
    """Get audio cache status"""
    data = load_dialogues()
    total_lines = 0
    cached_lines = 0
    
    for cat in data["categories"]:
        for s in cat["scenarios"]:
            if s["status"] != "ready":
                continue
            for line in s.get("lines", []):
                total_lines += 1
                text = line.get("text", "")
                h = hashlib.sha256(text.encode()).hexdigest()[:12]
                cache_path = TTS_CACHE_DIR / f"{h}.mp3"
                if cache_path.exists():
                    cached_lines += 1
    
    return jsonify({
        "total_lines": total_lines,
        "cached_lines": cached_lines,
        "percentage": round(cached_lines / max(total_lines, 1) * 100)
    })


# ---------------------------------------------------------------------------
# Learning Progress API
# ---------------------------------------------------------------------------
@app.route("/api/stats")
def api_stats():
    """Get overall learning statistics"""
    data = load_dialogues()
    db = get_db()
    
    # Get all viewed scenarios
    rows = db.execute(
        "SELECT scenario_id, MAX(viewed_at) as last_viewed, COUNT(*) as view_count FROM activity GROUP BY scenario_id"
    ).fetchall()
    viewed = {r["scenario_id"]: {"last_viewed": r["last_viewed"], "view_count": r["view_count"]} for r in rows}
    
    # Calculate statistics
    total_scenarios = 0
    ready_scenarios = 0
    viewed_scenarios = 0
    total_view_count = 0
    
    categories_stats = []
    
    for cat in data["categories"]:
        cat_total = len(cat["scenarios"])
        cat_ready = sum(1 for s in cat["scenarios"] if s["status"] == "ready")
        cat_viewed = sum(1 for s in cat["scenarios"] if s["id"] in viewed)
        cat_view_count = sum(viewed.get(s["id"], {}).get("view_count", 0) for s in cat["scenarios"])
        
        total_scenarios += cat_total
        ready_scenarios += cat_ready
        viewed_scenarios += cat_viewed
        total_view_count += cat_view_count
        
        categories_stats.append({
            "id": cat["id"],
            "name": cat["name"],
            "total": cat_total,
            "ready": cat_ready,
            "viewed": cat_viewed,
            "view_count": cat_view_count,
            "progress": round(cat_viewed / max(cat_ready, 1) * 100)
        })
    
    return jsonify({
        "total_scenarios": total_scenarios,
        "ready_scenarios": ready_scenarios,
        "viewed_scenarios": viewed_scenarios,
        "total_view_count": total_view_count,
        "progress": round(viewed_scenarios / max(ready_scenarios, 1) * 100),
        "categories": categories_stats
    })


@app.route("/api/category/<category_id>")
def api_category(category_id):
    """Get detailed category information"""
    data = load_dialogues()
    db = get_db()
    
    for cat in data["categories"]:
        if cat["id"] == category_id:
            # Get viewed status
            rows = db.execute(
                "SELECT scenario_id, MAX(viewed_at) as last_viewed, COUNT(*) as view_count FROM activity WHERE scenario_id IN (SELECT scenario_id FROM activity) GROUP BY scenario_id"
            ).fetchall()
            viewed = {r["scenario_id"]: {"last_viewed": r["last_viewed"], "view_count": r["view_count"]} for r in rows}
            
            scenarios = []
            for s in cat["scenarios"]:
                v = viewed.get(s["id"], {})
                scenarios.append({
                    "id": s["id"],
                    "title": s["title"],
                    "title_cn": s["title_cn"],
                    "difficulty": s["difficulty"],
                    "status": s["status"],
                    "characters": s.get("characters", []),
                    "viewed_at": v.get("last_viewed"),
                    "view_count": v.get("view_count", 0),
                    "is_viewed": s["id"] in viewed,
                    "lines_count": len(s.get("lines", [])),
                    "prev_id": s.get("prev_id"),
                    "next_id": s.get("next_id")
                })
            
            return jsonify({
                "id": cat["id"],
                "name": cat["name"],
                "name_cn": cat.get("name_cn", cat["name"]),
                "total": len(scenarios),
                "ready": sum(1 for s in scenarios if s["status"] == "ready"),
                "viewed": sum(1 for s in scenarios if s["is_viewed"]),
                "scenarios": scenarios
            })
    
    return jsonify({"error": "category not found"}), 404


@app.route("/api/scenario/<scenario_id>/detail")
def api_scenario_detail(scenario_id):
    """Get detailed scenario information without recording view"""
    data = load_dialogues()
    db = get_db()
    
    for cat in data["categories"]:
        for s in cat["scenarios"]:
            if s["id"] == scenario_id:
                # Get view statistics
                row = db.execute(
                    "SELECT MAX(viewed_at) as last_viewed, COUNT(*) as view_count FROM activity WHERE scenario_id=?",
                    (scenario_id,)
                ).fetchone()
                
                # Add hash for each line
                lines = []
                for line in s.get("lines", []):
                    lines.append({
                        "speaker": line.get("speaker"),
                        "text": line.get("text"),
                        "text_cn": line.get("text_cn"),
                        "hash": hashlib.sha256(line["text"].encode()).hexdigest()[:12]
                    })
                
                return jsonify({
                    "id": s["id"],
                    "title": s["title"],
                    "title_cn": s["title_cn"],
                    "difficulty": s["difficulty"],
                    "status": s["status"],
                    "characters": s.get("characters", []),
                    "category_id": cat["id"],
                    "category_name": cat["name"],
                    "viewed_at": row["last_viewed"] if row else None,
                    "view_count": row["view_count"] if row else 0,
                    "lines": lines,
                    "blanks": s.get("blanks", []),
                    "prev_id": s.get("prev_id"),
                    "next_id": s.get("next_id")
                })
    
    return jsonify({"error": "not found"}), 404


@app.route("/api/activity")
def api_activity():
    """Get recent activity log"""
    db = get_db()
    data = load_dialogues()
    
    # Build scenario lookup
    lookup = {}
    for cat in data["categories"]:
        for s in cat["scenarios"]:
            lookup[s["id"]] = {"title": s["title"], "title_cn": s["title_cn"], "category": cat["name"]}
    
    # Get recent activity
    limit = request.args.get("limit", 50, type=int)
    scenario_id = request.args.get("scenario_id")
    
    if scenario_id:
        rows = db.execute(
            "SELECT id, scenario_id, viewed_at FROM activity WHERE scenario_id=? ORDER BY viewed_at DESC LIMIT ?",
            (scenario_id, limit)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT id, scenario_id, viewed_at FROM activity ORDER BY viewed_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
    
    result = []
    for r in rows:
        info = lookup.get(r["scenario_id"], {})
        result.append({
            "id": r["id"],
            "scenario_id": r["scenario_id"],
            "scenario_title": info.get("title"),
            "scenario_title_cn": info.get("title_cn"),
            "category": info.get("category"),
            "viewed_at": r["viewed_at"]
        })
    
    return jsonify(result)


@app.route("/api/activity/summary")
def api_activity_summary():
    """Get activity summary by date"""
    db = get_db()
    
    # Get daily summary for last 30 days
    rows = db.execute(
        """
        SELECT date(viewed_at) as date, COUNT(*) as count, COUNT(DISTINCT scenario_id) as unique_scenarios
        FROM activity 
        WHERE viewed_at >= date('now', '-30 days')
        GROUP BY date(viewed_at)
        ORDER BY date DESC
        """
    ).fetchall()
    
    result = []
    for r in rows:
        result.append({
            "date": r["date"],
            "count": r["count"],
            "unique_scenarios": r["unique_scenarios"]
        })
    
    return jsonify(result)


@app.route("/api/export/data")
def api_export_data():
    """Export all learning data as JSON"""
    data = load_dialogues()
    db = get_db()
    
    # Get all activity
    rows = db.execute(
        "SELECT scenario_id, viewed_at FROM activity ORDER BY viewed_at"
    ).fetchall()
    
    activity = []
    for r in rows:
        activity.append({
            "scenario_id": r["scenario_id"],
            "viewed_at": r["viewed_at"]
        })
    
    return jsonify({
        "dialogues": data,
        "activity": activity,
        "exported_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    })


@app.route("/api/export/csv")
def api_export_csv():
    """Export learning data as CSV"""
    import io
    
    data = load_dialogues()
    db = get_db()
    
    # Get viewed status
    rows = db.execute(
        "SELECT scenario_id, MAX(viewed_at) as last_viewed, COUNT(*) as view_count FROM activity GROUP BY scenario_id"
    ).fetchall()
    viewed = {r["scenario_id"]: {"last_viewed": r["last_viewed"], "view_count": r["view_count"]} for r in rows}
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["category_id", "category_name", "scenario_id", "title", "title_cn", "difficulty", "status", "is_viewed", "view_count", "last_viewed"])
    
    for cat in data["categories"]:
        for s in cat["scenarios"]:
            v = viewed.get(s["id"], {})
            writer.writerow([
                cat["id"],
                cat["name"],
                s["id"],
                s["title"],
                s["title_cn"],
                s["difficulty"],
                s["status"],
                "yes" if s["id"] in viewed else "no",
                v.get("view_count", 0),
                v.get("last_viewed", "")
            ])
    
    response = send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"learning_progress_{datetime.now(CST).strftime('%Y%m%d')}.csv"
    )
    return response


@app.route("/api/health")
def api_health():
    """Health check endpoint"""
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
