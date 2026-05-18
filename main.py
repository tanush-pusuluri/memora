# MEMORA - AI Study Tool
# deployed on Render - set GROQ_API_KEY as an environment variable there
# to run locally: pip install -r requirements.txt, add GROQ_API_KEY to .env, then python3 main.py

import json
import os
import uuid

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, redirect, render_template, request, session, url_for
from groq import Groq

app = Flask(__name__)

app.secret_key = os.environ.get("FLASK_SECRET_KEY", "memora-dev-secret-123")

# in-memory store - keeps AI responses server-side since cookies have a 4KB limit
study_data: dict = {}


# Groq API helper

def ask_ai(prompt: str) -> str:
    client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    message = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.choices[0].message.content


def parse_json(response: str):
    response = response.strip()
    if "```json" in response:
        response = response.split("```json")[1].split("```")[0]
    elif "```" in response:
        response = response.split("```")[1].split("```")[0]
    return json.loads(response.strip())


# content generators - one for each study mode

def generate_flashcards(topic: str, count: int = 10, difficulty: str = "medium") -> list:
    level = {
        "easy": "basic recall and simple definitions",
        "medium": "understanding and application",
        "hard": "analysis, edge cases, and deep understanding",
    }.get(difficulty, "understanding and application")
    prompt = f"""Create exactly {count} flashcards for studying "{topic}" at {level} level.
Return ONLY a valid JSON array — no explanation, no markdown:
[{{"question": "Question?", "answer": "Answer."}}]
Keep each answer to 1-3 sentences."""
    return parse_json(ask_ai(prompt))


def generate_quiz(topic: str, difficulty: str = "medium") -> list:
    level = {
        "easy": "basic recall",
        "medium": "understanding and application",
        "hard": "analysis and synthesis",
    }.get(difficulty, "understanding and application")
    prompt = f"""Create exactly 8 multiple choice questions about "{topic}" at {level} level.
Return ONLY a valid JSON array — no explanation, no markdown:
[{{"question": "Question?", "options": ["Option A", "Option B", "Option C", "Option D"], "answer": "Option A", "explanation": "Why this is correct."}}]
The answer field must be the exact text of the correct option."""
    return parse_json(ask_ai(prompt))


def generate_brain_dump(topic: str) -> list:
    prompt = f"""List exactly 7 key concepts someone learning "{topic}" must understand.
Return ONLY a valid JSON array — no explanation, no markdown:
[{{"term": "Concept Name", "explanation": "Clear 2-3 sentence explanation."}}]"""
    return parse_json(ask_ai(prompt))


def generate_assessment(topic: str, weak_areas: list) -> dict:
    prompt = f"""A student studying "{topic}" left these concepts completely blank: {', '.join(weak_areas)}.
Return ONLY valid JSON — no explanation, no markdown:
{{"summary": "One sentence about what they need to focus on.", "tips": ["specific study tip 1", "specific study tip 2", "specific study tip 3"], "resources": [{{"name": "Resource name", "description": "What to search for or how to use this resource to learn the topic"}}]}}
For resources, only suggest well-known free platforms like Khan Academy, Crash Course on YouTube, or similar. Include exactly 3 resources."""
    return parse_json(ask_ai(prompt))


# session helpers

def get_session_id() -> str:
    if "sid" not in session:
        session["sid"] = uuid.uuid4().hex[:12]
    return session["sid"]


def get_data() -> dict:
    return study_data.get(get_session_id(), {})


def set_data(data: dict):
    study_data[get_session_id()] = data


# routes

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    topic = request.form.get("topic", "").strip()
    mode = request.form.get("mode", "")

    if not topic or mode not in ("flashcards", "quiz", "brain_dump"):
        return redirect(url_for("index"))

    if mode == "flashcards":
        try:
            count = min(25, max(5, int(request.form.get("card_count", 10))))
        except (ValueError, TypeError):
            count = 10
        difficulty = request.form.get("difficulty", "medium")
        cards = generate_flashcards(topic, count, difficulty)
        set_data({"topic": topic, "mode": mode, "cards": cards})
        return redirect(url_for("flashcards"))

    elif mode == "quiz":
        difficulty = request.form.get("difficulty", "medium")
        questions = generate_quiz(topic, difficulty)
        set_data({"topic": topic, "mode": mode, "questions": questions})
        return redirect(url_for("quiz"))

    elif mode == "brain_dump":
        concepts = generate_brain_dump(topic)
        set_data({"topic": topic, "mode": mode, "concepts": concepts})
        return redirect(url_for("brain_dump"))


# flashcards route

@app.route("/flashcards")
def flashcards():
    d = get_data()
    if not d or d.get("mode") != "flashcards":
        return redirect(url_for("index"))
    return render_template("flashcards.html", topic=d["topic"], cards=d["cards"])


# quiz route

@app.route("/quiz", methods=["GET", "POST"])
def quiz():
    d = get_data()
    if not d or d.get("mode") != "quiz":
        return redirect(url_for("index"))

    questions = d["questions"]

    if request.method == "POST":
        user_answers = {}
        for i in range(len(questions)):
            user_answers[i] = request.form.get(f"answer_{i}", "")
        score = sum(1 for i, q in enumerate(questions) if user_answers.get(i) == q["answer"])
        return render_template(
            "quiz.html",
            topic=d["topic"],
            questions=questions,
            user_answers=user_answers,
            score=score,
            show_results=True,
        )

    return render_template("quiz.html", topic=d["topic"], questions=questions, show_results=False)


# brain dump route

@app.route("/brain_dump", methods=["GET", "POST"])
def brain_dump():
    d = get_data()
    if not d or d.get("mode") != "brain_dump":
        return redirect(url_for("index"))

    concepts = d["concepts"]
    user_responses = {}

    if request.method == "POST":
        for i in range(len(concepts)):
            text = request.form.get(f"response_{i}", "").strip()
            user_responses[i] = text or "(left blank)"

        weak_areas = [concepts[i]["term"] for i in range(len(concepts)) if user_responses[i] == "(left blank)"]
        assessment = generate_assessment(d["topic"], weak_areas) if weak_areas else None

        return render_template(
            "brain_dump.html",
            topic=d["topic"],
            concepts=concepts,
            user_responses=user_responses,
            show_results=True,
            assessment=assessment,
        )

    return render_template("brain_dump.html", topic=d["topic"], concepts=concepts, show_results=False)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
