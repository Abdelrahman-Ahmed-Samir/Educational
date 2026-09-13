import json
import sys
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).parent.parent
sys.path.append(str(APP_DIR))
from utils.sheets import count_attempts, record_result, sheets_configured  # noqa: E402
from utils.ui import apply_theme, badge, render_header  # noqa: E402

st.set_page_config(page_title="Quizzes", page_icon="📝")
apply_theme()

QUIZZES_DIR = APP_DIR / "quizzes"

TYPE_LABELS = {
    "mcq": "Multiple choice",
    "true_false": "True or false",
    "short_answer": "Short answer",
    "fill_blank": "Fill in the blank",
    "select_all": "Select all that apply",
    "classify": "Classify",
    "open_ended": "Open ended",
}


def load_questions():
    """Load every quiz file in quizzes/, one .json file per topic.

    Each file is self-contained: {"title": "...", "time_limit_minutes": N,
    "questions": [...], "max_attempts": N (optional)}. Keyed by each file's
    own "title"; files are read in filename order — prefix with 01_, 02_
    etc. to control the order topics appear in.
    """
    quizzes = {}
    for path in sorted(QUIZZES_DIR.glob("*.json")):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        title = data.get("title", path.stem)
        quizzes[title] = data
    return quizzes


def question_points(q: dict) -> int:
    """How many auto-gradable points a question is worth."""
    if q["type"] == "classify":
        return len(q["items"])
    if q["type"] == "select_all":
        return len(q["answer_indices"])
    if q["type"] == "open_ended":
        return 0
    return 1


def is_answered(q: dict, i: int) -> bool:
    if q["type"] == "classify":
        return all(st.session_state.get(f"q_{i}_{j}") for j in range(len(q["items"])))
    val = st.session_state.get(f"q_{i}")
    if val is None:
        return False
    if isinstance(val, str):
        return bool(val.strip())
    if isinstance(val, list):
        return len(val) > 0
    return True


def finalize_quiz(topic: str, data: dict, total_points: int):
    """Score whatever has been answered so far and move to the result stage."""
    score = 0
    open_ended_notes = []
    review_items = []

    for i, q in enumerate(data["questions"]):
        qtype = q["type"]

        if qtype == "mcq":
            picked = st.session_state.get(f"q_{i}")
            is_correct = picked is not None and q["options"].index(picked) == q["answer_index"]
            if is_correct:
                score += 1
            review_items.append({
                "question": q["question"],
                "your_answer": picked or "No answer",
                "correct_answer": q["options"][q["answer_index"]],
                "status": "correct" if is_correct else "incorrect",
            })

        elif qtype == "true_false":
            picked = st.session_state.get(f"q_{i}")
            is_correct = picked is not None and (picked == "True") == q["answer"]
            if is_correct:
                score += 1
            review_items.append({
                "question": q["question"],
                "your_answer": picked or "No answer",
                "correct_answer": "True" if q["answer"] else "False",
                "status": "correct" if is_correct else "incorrect",
            })

        elif qtype in ("short_answer", "fill_blank"):
            picked_text = (st.session_state.get(f"q_{i}") or "").strip()
            is_correct = picked_text.lower() in [a.lower() for a in q["accepted_answers"]]
            if is_correct:
                score += 1
            review_items.append({
                "question": q["question"],
                "your_answer": picked_text or "No answer",
                "correct_answer": " / ".join(q["accepted_answers"]),
                "status": "correct" if is_correct else "incorrect",
            })

        elif qtype == "select_all":
            picked_options = st.session_state.get(f"q_{i}") or []
            picked_indices = {q["options"].index(opt) for opt in picked_options}
            correct_indices = set(q["answer_indices"])
            is_correct = picked_indices == correct_indices
            if is_correct:
                score += len(correct_indices)
            review_items.append({
                "question": q["question"],
                "your_answer": ", ".join(picked_options) if picked_options else "No answer",
                "correct_answer": ", ".join(q["options"][idx] for idx in sorted(correct_indices)),
                "status": "correct" if is_correct else "incorrect",
            })

        elif qtype == "classify":
            sub_lines = []
            all_correct = True
            for j, item in enumerate(q["items"]):
                picked_cat = st.session_state.get(f"q_{i}_{j}")
                is_correct = picked_cat is not None and q["categories"].index(picked_cat) == item["answer_index"]
                if is_correct:
                    score += 1
                else:
                    all_correct = False
                icon = "✅" if is_correct else "❌"
                sub_lines.append(
                    f"{icon} *{item['text']}* — you said **{picked_cat or 'no answer'}**"
                    + ("" if is_correct else f", correct is **{q['categories'][item['answer_index']]}**")
                )
            review_items.append({
                "question": q["question"],
                "sub_lines": sub_lines,
                "status": "correct" if all_correct else "incorrect",
            })

        elif qtype == "open_ended":
            answer_text = (st.session_state.get(f"q_{i}") or "").strip()
            open_ended_notes.append(
                f"Q{i + 1}: {q['question']}\nStudent answer: {answer_text or '(left blank)'}\n"
                f"Model answer: {q['model_answer']}"
            )
            review_items.append({
                "question": q["question"],
                "your_answer": answer_text or "(left blank)",
                "correct_answer": q["model_answer"],
                "status": "review",
            })

    st.session_state.quiz_score = score
    st.session_state.quiz_total = total_points
    st.session_state.quiz_open_notes = "\n\n".join(open_ended_notes)
    st.session_state.quiz_review = review_items

    if sheets_configured():
        try:
            record_result(
                st.session_state.quiz_student_name,
                topic,
                score,
                total_points,
                st.session_state.quiz_open_notes,
            )
            st.session_state.quiz_synced = True
        except Exception as e:  # noqa: BLE001
            st.session_state.quiz_synced = False
            st.session_state.quiz_sync_error = str(e)
    else:
        st.session_state.quiz_synced = False

    st.session_state.quiz_stage = "result"


questions_by_topic = load_questions()

if "quiz_stage" not in st.session_state:
    st.session_state.quiz_stage = "pick_topic"

render_header("Pick a topic, take the exam, and your score is saved automatically.")

if not sheets_configured():
    st.info(
        "Google Sheet isn't connected yet, so scores won't be saved. "
        "Add the credentials in `.streamlit/secrets.toml` (see README.md) to enable that.",
        icon="ℹ️",
    )

# ---- Stage 1: pick a topic ----
if st.session_state.quiz_stage == "pick_topic":
    student_name = st.text_input("Your name", key="student_name")
    topic = st.selectbox("Topic", list(questions_by_topic.keys()))

    max_attempts = questions_by_topic[topic].get("max_attempts")
    attempts_used = 0
    limit_reached = False
    if max_attempts and sheets_configured() and student_name.strip():
        attempts_used = count_attempts(student_name.strip(), topic)
        limit_reached = attempts_used >= max_attempts
        if limit_reached:
            st.error(
                f"You've already used all {max_attempts} attempt(s) for this quiz "
                f"under the name '{student_name.strip()}'."
            )
        else:
            st.caption(f"Attempt {attempts_used + 1} of {max_attempts}.")

    if st.button("Start exam", type="primary", disabled=limit_reached):
        if not student_name.strip():
            st.error("Enter your name first.")
        else:
            st.session_state.quiz_topic = topic
            st.session_state.quiz_stage = "taking"
            st.session_state.quiz_student_name = student_name.strip()
            st.rerun()

# ---- Stage 2: take the exam ----
elif st.session_state.quiz_stage == "taking":
    topic = st.session_state.quiz_topic
    data = questions_by_topic[topic]
    total_points = sum(question_points(q) for q in data["questions"])

    st.subheader(topic)
    st.caption(f"{len(data['questions'])} questions · {total_points} auto-graded points")

    with st.form("exam_form"):
        for i, q in enumerate(data["questions"]):
            label = TYPE_LABELS.get(q["type"], "")
            st.markdown(f"{badge(label, 'type')}", unsafe_allow_html=True)
            st.write(f"**Q{i + 1}.** {q['question']}")

            if q["type"] == "mcq":
                st.radio(
                    "Choose one", q["options"], key=f"q_{i}", index=None,
                    label_visibility="collapsed",
                )

            elif q["type"] == "true_false":
                st.radio(
                    "True or false", ["True", "False"], key=f"q_{i}", index=None,
                    label_visibility="collapsed",
                )

            elif q["type"] == "short_answer":
                st.text_input("Your answer", key=f"q_{i}", label_visibility="collapsed")

            elif q["type"] == "fill_blank":
                st.text_input("Fill in the blank", key=f"q_{i}", label_visibility="collapsed")

            elif q["type"] == "select_all":
                st.multiselect(
                    "Choose all that apply", q["options"], key=f"q_{i}",
                    label_visibility="collapsed",
                )

            elif q["type"] == "classify":
                for j, item in enumerate(q["items"]):
                    st.caption(item["text"])
                    st.selectbox(
                        "Category", q["categories"], key=f"q_{i}_{j}", index=None,
                        label_visibility="collapsed",
                    )

            elif q["type"] == "open_ended":
                st.text_area("Your answer", key=f"q_{i}", label_visibility="collapsed")

            st.write("")

        submitted = st.form_submit_button("Submit exam", type="primary")

    if submitted:
        missing = any(not is_answered(q, i) for i, q in enumerate(data["questions"]))
        if missing:
            st.error("Answer every question before submitting.")
        else:
            finalize_quiz(topic, data, total_points)
            st.rerun()

    if st.button("Back to topics"):
        st.session_state.quiz_stage = "pick_topic"
        st.rerun()

# ---- Stage 3: result ----
elif st.session_state.quiz_stage == "result":
    score = st.session_state.quiz_score
    total = st.session_state.quiz_total
    st.caption(f"Submitted by {st.session_state.get('quiz_student_name', 'you')}")
    st.metric("Auto-graded score", f"{score}/{total}")

    if st.session_state.get("quiz_synced"):
        st.success("Synced to the Google Sheet.", icon="✅")
    elif sheets_configured():
        st.error(f"Couldn't sync to the sheet: {st.session_state.get('quiz_sync_error', 'unknown error')}")
    else:
        st.warning("Not saved — the Google Sheet isn't connected.")

    st.write("")
    st.subheader("Review your answers")

    status_labels = {"correct": "Correct", "incorrect": "Incorrect", "review": "Needs review"}

    for i, item in enumerate(st.session_state.get("quiz_review", [])):
        with st.container(border=True):
            st.markdown(
                f"{badge(status_labels[item['status']], item['status'])}",
                unsafe_allow_html=True,
            )
            st.markdown(f"**Q{i + 1}.** {item['question']}")

            if "sub_lines" in item:
                for line in item["sub_lines"]:
                    st.markdown(line)
            elif item["status"] == "review":
                st.markdown(f"Your answer: {item['your_answer']}")
                st.caption(f"Model answer (for self-checking): {item['correct_answer']}")
            else:
                st.markdown(f"Your answer: **{item['your_answer']}**")
                if item["status"] == "incorrect":
                    st.markdown(f"Correct answer: **{item['correct_answer']}**")

    if st.button("Back to topics"):
        st.session_state.quiz_stage = "pick_topic"
        st.rerun()