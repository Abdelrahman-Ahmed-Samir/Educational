import json
import sys
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).parent.parent
sys.path.append(str(APP_DIR))
from utils.sheets import record_result, sheets_configured  # noqa: E402
from utils.ui import apply_theme, badge, render_header  # noqa: E402

st.set_page_config(page_title="Quizzes", page_icon="📝")
apply_theme()

QUESTIONS_PATH = APP_DIR / "quizzes" / "questions.json"


def load_questions():
    with open(QUESTIONS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def question_points(q: dict) -> int:
    """How many auto-gradable points a question is worth."""
    if q["type"] == "classify":
        return len(q["items"])
    if q["type"] == "open_ended":
        return 0
    return 1


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

    if st.button("Start exam", type="primary"):
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
    st.caption(
        f"{len(data['questions'])} questions · {total_points} auto-graded points "
        f"· {data['time_limit_minutes']} min"
    )

    with st.form("exam_form"):
        type_labels = {
            "mcq": ("Multiple choice", "type"),
            "true_false": ("True or false", "type"),
            "short_answer": ("Short answer", "type"),
            "classify": ("Classify", "type"),
            "open_ended": ("Open ended", "type"),
        }

        for i, q in enumerate(data["questions"]):
            label, kind = type_labels.get(q["type"], ("", "type"))
            st.markdown(f"{badge(label, kind)}", unsafe_allow_html=True)
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
        missing = False
        for i, q in enumerate(data["questions"]):
            if q["type"] == "classify":
                for j in range(len(q["items"])):
                    if not st.session_state.get(f"q_{i}_{j}"):
                        missing = True
            else:
                val = st.session_state.get(f"q_{i}")
                if val is None or (isinstance(val, str) and not val.strip()):
                    missing = True

        if missing:
            st.error("Answer every question before submitting.")
        else:
            score = 0
            open_ended_notes = []

            for i, q in enumerate(data["questions"]):
                qtype = q["type"]

                if qtype == "mcq":
                    picked = st.session_state[f"q_{i}"]
                    if q["options"].index(picked) == q["answer_index"]:
                        score += 1

                elif qtype == "true_false":
                    picked_bool = st.session_state[f"q_{i}"] == "True"
                    if picked_bool == q["answer"]:
                        score += 1

                elif qtype == "short_answer":
                    picked_text = st.session_state[f"q_{i}"].strip().lower()
                    if picked_text in [a.lower() for a in q["accepted_answers"]]:
                        score += 1

                elif qtype == "classify":
                    for j, item in enumerate(q["items"]):
                        picked_cat = st.session_state[f"q_{i}_{j}"]
                        if q["categories"].index(picked_cat) == item["answer_index"]:
                            score += 1

                elif qtype == "open_ended":
                    answer_text = st.session_state[f"q_{i}"].strip()
                    open_ended_notes.append(
                        f"Q{i + 1}: {q['question']}\nStudent answer: {answer_text}\n"
                        f"Model answer: {q['model_answer']}"
                    )

            st.session_state.quiz_score = score
            st.session_state.quiz_total = total_points
            st.session_state.quiz_open_notes = "\n\n".join(open_ended_notes)

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

    if st.session_state.get("quiz_open_notes"):
        st.divider()
        st.caption(
            "Open-ended questions aren't auto-graded. Your teacher will review these; "
            "here's the model answer for self-checking."
        )
        with st.expander("Review your open-ended answers"):
            st.text(st.session_state.quiz_open_notes)

    if st.button("Back to topics"):
        st.session_state.quiz_stage = "pick_topic"
        st.rerun()
