# MEMORA - AI Study Tool
# deployed on Vercel - set GROQ_API_KEY as an environment variable in the Vercel dashboard
# to run locally: pip install -r requirements.txt, add GROQ_API_KEY to .env, then python3 main.py

import json
import os
import uuid
from urllib.parse import quote_plus

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, redirect, render_template, request, session, url_for
from groq import Groq

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "memora-dev-secret-123")

# in-memory store - keeps AI responses server-side since cookies have a 4KB limit
study_data: dict = {}


# Groq API helper

def ask_ai(prompt: str, max_tokens: int = 2048) -> str:
    client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    message = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=max_tokens,
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


# content moderation

def is_appropriate_topic(topic: str) -> bool:
    prompt = f"""Is the following study topic appropriate for middle school students (ages 11-14) to study academically?

Topic: "{topic}"

Answer YES for legitimate academic topics: history, science, math, literature, social issues, LGBTQ history, health, biology, religion, politics, classic novels, etc.
Also answer YES if a word that could be an expletive appears as part of a well-known academic work or proper noun (e.g. "Moby Dick", "The Catcher in the Rye", "Dick Cheney").

Answer NO if:
- The topic is just an expletive or slur by itself with no academic context
- The topic is clearly sexual, pornographic, or grossly offensive with no educational value
- The topic asks for instructions for illegal or dangerous activities

When in doubt about a borderline word, consider whether a middle school English or history teacher would assign it. If yes, answer YES.

Reply with only YES or NO."""
    try:
        result = ask_ai(prompt, max_tokens=10)
        return "NO" not in result.strip().upper()[:5]
    except Exception:
        return True  # fail open so errors don't block students


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


def generate_quiz(topic: str, count: int = 8, difficulty: str = "medium") -> list:
    level = {
        "easy": "basic recall",
        "medium": "understanding and application",
        "hard": "analysis and synthesis",
    }.get(difficulty, "understanding and application")
    prompt = f"""Create exactly {count} multiple choice questions about "{topic}" at {level} level.
Return ONLY a valid JSON array — no explanation, no markdown:
[{{"question": "Question?", "options": ["Option A", "Option B", "Option C", "Option D"], "answer": "Option A", "explanation": "Why this is correct."}}]
The answer field must be the exact text of the correct option."""
    return parse_json(ask_ai(prompt))


def generate_quiz_more(topic: str, difficulty: str, previous_questions: list) -> list:
    level = {
        "easy": "basic recall",
        "medium": "understanding and application",
        "hard": "analysis and synthesis",
    }.get(difficulty, "understanding and application")
    prev_str = "\n".join(f"- {q['question']}" for q in previous_questions)
    prompt = f"""Create exactly 10 NEW multiple choice questions about "{topic}" at {level} level.
Do NOT repeat or rephrase any of these already-asked questions:
{prev_str}

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
    prompt = f"""A student studying "{topic}" is struggling with these specific concepts: {', '.join(weak_areas)}.

Return ONLY valid JSON — no explanation, no markdown:
{{"summary": "One sentence about what they need to focus on.", "tips": ["tip 1", "tip 2", "tip 3"], "resources": [{{"name": "Resource name", "type": "youtube or website", "search_query": "what to search for on that platform", "description": "one sentence on how this helps"}}]}}

Pick 3 resources that genuinely fit the subject. Vary them — do not always pick the same ones. Choose from this pool:

YouTube channels (type: "youtube"): Khan Academy, TED-Ed, Kurzgesagt, Veritasium, CGP Grey, SciShow, Extra History, Tom Scott, 3Blue1Brown, PBS Space Time, Numberphile, Vsauce, AsapSCIENCE, Crash Course (use sparingly)

Websites (type: "website"): Khan Academy, Britannica, Wikipedia, National Geographic, Smithsonian Magazine, NASA, HISTORY.com, SparkNotes, MIT OpenCourseWare, Scientific American, Stanford Encyclopedia of Philosophy, BBC (use sparingly), The New York Times Learning Network, Newsela

Match resources to the subject. The search_query should be a short phrase that finds the most relevant content for the weak concepts on that specific resource."""
    return parse_json(ask_ai(prompt))


def add_resource_urls(assessment: dict, topic: str) -> dict:
    if not assessment:
        return assessment
    for resource in assessment.get("resources", []):
        query = quote_plus(f"{resource.get('name', '')} {resource.get('search_query', topic)}")
        if resource.get("type") == "youtube":
            resource["url"] = f"https://www.youtube.com/results?search_query={query}"
        else:
            resource["url"] = f"https://www.google.com/search?q={query}"
    return assessment


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
    error = request.args.get("error", "")
    return render_template("index.html", error=error)


@app.route("/generate", methods=["POST"])
def generate():
    topic = request.form.get("topic", "").strip()
    mode = request.form.get("mode", "")

    if not topic or mode not in ("flashcards", "quiz", "brain_dump"):
        return redirect(url_for("index"))

    if not is_appropriate_topic(topic):
        return redirect(url_for("index", error="inappropriate"))

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
        try:
            count = min(20, max(5, int(request.form.get("quiz_count", 8))))
        except (ValueError, TypeError):
            count = 8
        difficulty = request.form.get("difficulty", "medium")
        questions = generate_quiz(topic, count, difficulty)
        set_data({"topic": topic, "mode": mode, "questions": questions, "difficulty": difficulty})
        return redirect(url_for("quiz"))

    elif mode == "brain_dump":
        concepts = generate_brain_dump(topic)
        set_data({"topic": topic, "mode": mode, "concepts": concepts})
        return redirect(url_for("brain_dump"))


# flashcards routes

@app.route("/flashcards")
def flashcards():
    d = get_data()
    if not d or d.get("mode") != "flashcards":
        return redirect(url_for("index"))
    return render_template("flashcards.html", topic=d["topic"], cards=d["cards"])


@app.route("/flashcards_review", methods=["POST"])
def flashcards_review():
    d = get_data()
    if not d or d.get("mode") != "flashcards":
        return redirect(url_for("index"))

    cards = d["cards"]
    indices = request.form.getlist("still_learning")
    weak_cards = [cards[int(i)] for i in indices if i.isdigit() and int(i) < len(cards)]
    weak_areas = [c["question"] for c in weak_cards]
    assessment = add_resource_urls(generate_assessment(d["topic"], weak_areas), d["topic"]) if weak_areas else None

    return render_template(
        "flashcards_review.html",
        topic=d["topic"],
        weak_cards=weak_cards,
        assessment=assessment,
    )


# quiz routes

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

        wrong = [q for i, q in enumerate(questions) if user_answers.get(i) != q["answer"]]
        weak_areas = [q["question"] for q in wrong]
        assessment = add_resource_urls(generate_assessment(d["topic"], weak_areas), d["topic"]) if wrong else None

        return render_template(
            "quiz.html",
            topic=d["topic"],
            questions=questions,
            user_answers=user_answers,
            score=score,
            show_results=True,
            assessment=assessment,
        )

    return render_template("quiz.html", topic=d["topic"], questions=questions, show_results=False)


@app.route("/quiz_more", methods=["POST"])
def quiz_more():
    d = get_data()
    if not d or d.get("mode") != "quiz":
        return redirect(url_for("index"))

    new_questions = generate_quiz_more(d["topic"], d.get("difficulty", "medium"), d["questions"])
    d["questions"] = new_questions
    set_data(d)
    return redirect(url_for("quiz"))


# brain dump route

@app.route("/brain_dump", methods=["GET", "POST"])
def brain_dump():
    d = get_data()
    if not d or d.get("mode") != "brain_dump":
        return redirect(url_for("index"))

    concepts = d["concepts"]

    if request.method == "POST":
        action = request.form.get("action", "step2")

        if action == "step1":
            step1 = {}
            for i in range(len(concepts)):
                text = request.form.get(f"response_{i}", "").strip()
                step1[i] = text or "(left blank)"
            d["step1_responses"] = step1
            set_data(d)
            return render_template("brain_dump.html",
                topic=d["topic"], concepts=concepts, step=2, show_results=False)

        else:
            user_responses = {}
            for i in range(len(concepts)):
                text = request.form.get(f"response_{i}", "").strip()
                user_responses[i] = text or "(left blank)"

            weak_areas = [concepts[i]["term"] for i in range(len(concepts)) if user_responses[i] == "(left blank)"]
            assessment = add_resource_urls(generate_assessment(d["topic"], weak_areas), d["topic"]) if weak_areas else None

            return render_template("brain_dump.html",
                topic=d["topic"], concepts=concepts,
                user_responses=user_responses, show_results=True, assessment=assessment)

    return render_template("brain_dump.html", topic=d["topic"], concepts=concepts, step=1, show_results=False)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
