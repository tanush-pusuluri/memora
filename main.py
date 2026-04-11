# ============================================================
# MEMORA — AI Study Tool
# ============================================================
# To run:
#   1. pip install -r requirements.txt
#   2. Add GROQ_API_KEY="your-key-here" to .env
#   3. python3 main.py
#   4. Open http://localhost:5000 in your browser
# ============================================================

import json
import os
import uuid

from dotenv import load_dotenv
load_dotenv()  # reads the .env file and loads your API key

from flask import Flask, redirect, render_template, request, session, url_for
from groq import Groq

app = Flask(__name__)

# Secret key for encrypting the session cookie.
# Change this to any random string for real use.
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "memora-dev-secret-123")

# ── In-memory store ──────────────────────────────────────────
# Flask's default session stores data in the browser cookie,
# which has a ~4 KB size limit. We keep the big AI responses
# here instead, and only store a short session_id in the cookie.
study_data: dict = {}


# ── Groq helper ──────────────────────────────────────────────

def ask_ai(prompt: str) -> str:
    """Send a prompt to Groq and return the plain-text response."""
    client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    message = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.choices[0].message.content


def parse_json(response: str):
    """
    Parse JSON out of Claude's response.
    Claude sometimes wraps JSON in ```json ... ``` markdown — this strips that.
    """
    response = response.strip()
    if "```json" in response:
        response = response.split("```json")[1].split("```")[0]
    elif "```" in response:
        response = response.split("```")[1].split("```")[0]
    return json.loads(response.strip())


# ── Content generators ───────────────────────────────────────

def generate_flashcards(topic: str) -> list:
    prompt = f"""Create exactly 10 flashcards for studying "{topic}".
Return ONLY a valid JSON array — no explanation, no markdown:
[{{"question": "Question?", "answer": "Answer."}}]
Keep each answer to 1-3 sentences."""
    return parse_json(ask_ai(prompt))


def generate_study_guide(topic: str) -> list:
    prompt = f"""Create a study guide for "{topic}" with exactly 5 sections.
Return ONLY a valid JSON array — no explanation, no markdown:
[{{"title": "Section Title", "content": "2-3 paragraph explanation of this section."}}]
Make each section focused and clear."""
    return parse_json(ask_ai(prompt))


def generate_brain_dump(topic: str) -> list:
    prompt = f"""List exactly 7 key concepts someone learning "{topic}" must understand.
Return ONLY a valid JSON array — no explanation, no markdown:
[{{"term": "Concept Name", "explanation": "Clear 2-3 sentence explanation."}}]"""
    return parse_json(ask_ai(prompt))


# ── Session helpers ──────────────────────────────────────────

def get_session_id() -> str:
    """Get (or create) a unique ID for this browser session."""
    if "sid" not in session:
        session["sid"] = uuid.uuid4().hex[:12]
    return session["sid"]


def get_data() -> dict:
    return study_data.get(get_session_id(), {})


def set_data(data: dict):
    study_data[get_session_id()] = data


# ── Routes ───────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    """
    Called when the user submits the home form.
    Generates content with Claude and stores it, then redirects to the right mode.
    """
    topic = request.form.get("topic", "").strip()
    mode = request.form.get("mode", "")

    if not topic or mode not in ("flashcards", "study_guide", "brain_dump"):
        return redirect(url_for("index"))

    if mode == "flashcards":
        cards = generate_flashcards(topic)
        set_data({"topic": topic, "mode": mode, "cards": cards})
        return redirect(url_for("flashcards"))

    elif mode == "study_guide":
        sections = generate_study_guide(topic)
        set_data({
            "topic": topic,
            "mode": mode,
            "sections": sections,
            "section_idx": 0,
            "user_sections": [],   # what the user wrote for each section
            "show_ai": False,
        })
        return redirect(url_for("study_guide"))

    elif mode == "brain_dump":
        concepts = generate_brain_dump(topic)
        set_data({"topic": topic, "mode": mode, "concepts": concepts})
        return redirect(url_for("brain_dump"))


# ── Flashcards ───────────────────────────────────────────────

@app.route("/flashcards")
def flashcards():
    d = get_data()
    if not d or d.get("mode") != "flashcards":
        return redirect(url_for("index"))
    return render_template("flashcards.html", topic=d["topic"], cards=d["cards"])


# ── Study Guide ──────────────────────────────────────────────

@app.route("/study_guide", methods=["GET", "POST"])
def study_guide():
    d = get_data()
    if not d or d.get("mode") != "study_guide":
        return redirect(url_for("index"))

    sections = d["sections"]
    idx = d["section_idx"]
    user_sections = d["user_sections"]

    if request.method == "POST":
        action = request.form.get("action")

        if action == "submit_section":
            # User finished writing their version — save it, show AI version
            user_text = request.form.get("user_text", "").strip() or "(left blank)"
            user_sections.append(user_text)
            d["user_sections"] = user_sections
            d["show_ai"] = True
            set_data(d)

        elif action == "next_section":
            # Move to the next section (or finish)
            d["section_idx"] = idx + 1
            d["show_ai"] = False
            idx = d["section_idx"]
            set_data(d)

    # Re-read in case we just updated
    d = get_data()
    idx = d["section_idx"]

    done = idx >= len(sections)
    return render_template(
        "study_guide.html",
        topic=d["topic"],
        sections=sections,
        idx=idx,
        user_sections=d["user_sections"],
        show_ai=d["show_ai"],
        done=done,
    )


# ── Brain Dump ───────────────────────────────────────────────

@app.route("/brain_dump", methods=["GET", "POST"])
def brain_dump():
    d = get_data()
    if not d or d.get("mode") != "brain_dump":
        return redirect(url_for("index"))

    concepts = d["concepts"]
    user_responses = {}

    if request.method == "POST":
        # Collect what the user wrote for each concept
        for i in range(len(concepts)):
            text = request.form.get(f"response_{i}", "").strip()
            user_responses[i] = text or "(left blank)"
        return render_template(
            "brain_dump.html",
            topic=d["topic"],
            concepts=concepts,
            user_responses=user_responses,
            show_results=True,
        )

    return render_template(
        "brain_dump.html",
        topic=d["topic"],
        concepts=concepts,
        show_results=False,
    )


# ── Run ──────────────────────────────────────────────────────

if __name__ == "__main__":
    # debug=True auto-reloads when you save the file
    app.run(host="0.0.0.0", port=5000, debug=False)
