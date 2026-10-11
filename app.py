import json
import re
import unicodedata
from datetime import date
from pathlib import Path

import ollama
import streamlit as st
st.set_page_config(
    page_title="GetOut",
    page_icon="🌍",
    layout="centered"
)


# ==========================================
# CONFIGURATION
# ==========================================

PROGRESS_FILE = Path("progress.json")
DEFAULT_GEMS = 10
MODEL_NAME = "qwen2.5:1.5b"
DAILY_REWARD = 3

CATEGORIES = [
    "🌿 Nature",
    "🌙 Astronomy",
    "🔬 Science",
    "🗺️ Exploration",
    "🎨 Creativity",
]

CATEGORY_KEYWORDS = {
    "🌿 Nature": [
        "nature", "leaf", "leaves", "tree", "flower", "plant",
        "bird", "seed", "garden", "grass", "natural", "soil",
        "petal", "bark", "insect", "outdoor"
    ],
    "🌙 Astronomy": [
        "moon", "star", "planet", "sky", "sunset", "sunrise",
        "constellation", "astronomy", "cloud", "night sky"
    ],
    "🔬 Science": [
        "science", "shadow", "light", "sound", "motion", "water",
        "rolling", "balance", "wind", "drying", "brightness",
        "sunny", "shaded", "temperature", "reflection"
    ],
    "🗺️ Exploration": [
        "explore", "map", "landmark", "direction", "route",
        "surroundings", "nearby", "location", "pattern", "surface"
    ],
    "🎨 Creativity": [
        "draw", "drawing", "sketch", "create", "creative",
        "art", "story", "poem", "color", "colour", "design"
    ],
}


# ==========================================
# PROGRESS STORAGE
# ==========================================

def load_progress():
    defaults = {
        "gems": DEFAULT_GEMS,
        "streak": 0,
        "badges": [],
        "last_completed_date": None,
        "quest_history": [],
        "daily_quest": "",
        "quest_date": None,
        "quest_category": None,
        "completed_quest_date": None,
        "daily_feedback": "",
        "current_quest_completed": False,
        "current_quest_rewarded": False,
    }

    if not PROGRESS_FILE.exists():
        return defaults

    try:
        with PROGRESS_FILE.open("r", encoding="utf-8") as file:
            saved = json.load(file)

        if not isinstance(saved, dict):
            return defaults

        for key, value in defaults.items():
            if key not in saved:
                saved[key] = value

        if not isinstance(saved["quest_history"], list):
            saved["quest_history"] = []

        if not isinstance(saved["badges"], list):
            saved["badges"] = []

        return saved

    except (OSError, json.JSONDecodeError):
        return defaults


def parse_saved_date(value):
    if not value:
        return None

    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def save_progress():
    progress = {
        "gems": st.session_state.gems,
        "streak": st.session_state.streak,
        "badges": st.session_state.badges,
        "last_completed_date": (
            st.session_state.last_completed_date.isoformat()
            if st.session_state.last_completed_date
            else None
        ),
        "quest_history": st.session_state.quest_history,
        "daily_quest": st.session_state.ai_quest,
        "quest_date": (
            st.session_state.quest_date.isoformat()
            if st.session_state.quest_date
            else None
        ),
        "quest_category": st.session_state.quest_category,
        "completed_quest_date": (
            st.session_state.completed_quest_date.isoformat()
            if st.session_state.completed_quest_date
            else None
        ),
        "daily_feedback": st.session_state.daily_feedback,
        "current_quest_completed": (
            st.session_state.completed_quest_date == date.today()
            and bool(st.session_state.ai_quest)
        ),
        "current_quest_rewarded": (
            st.session_state.completed_quest_date == date.today()
            and bool(st.session_state.ai_quest)
        ),
    }

    with PROGRESS_FILE.open("w", encoding="utf-8") as file:
        json.dump(progress, file, indent=4, ensure_ascii=False)


# ==========================================
# TEXT VALIDATION
# ==========================================

def is_english_script(text):
    """Reject non-Latin writing systems while allowing punctuation and emoji."""
    for character in text:
        if unicodedata.category(character).startswith("L"):
            character_name = unicodedata.name(character, "")

            if "LATIN" not in character_name:
                return False

    return True


def get_quest_title(quest):
    match = re.search(
        r"Quest Title:\s*(.+)",
        quest,
        flags=re.IGNORECASE,
    )

    if match:
        return match.group(1).strip().strip("*# ")

    return "Untitled Quest"


def validate_quest(quest, category):
    if not quest or len(quest) < 100 or len(quest) > 3500:
        return False

    if not is_english_script(quest):
        return False

    required_sections = [
        "Quest Title:",
        "What to Do:",
        "Question 1:",
        "Question 2:",
        "Question 3:",
    ]

    lowered = quest.lower()

    if not all(section.lower() in lowered for section in required_sections):
        return False

    title = get_quest_title(quest)

    if len(title) < 5 or len(title) > 100:
        return False

    # Reject astronomy activities in unrelated categories.
    if category != "🌙 Astronomy":
        astronomy_phrases = [
            "observe the moon",
            "moon phase",
            "constellation",
            "identify planets",
            "observe the stars",
        ]

        if any(phrase in lowered for phrase in astronomy_phrases):
            return False

    # Comparing natural sunlight with a flashlight is misleading.
    if (
        "shaded area" in lowered
        and "sunny area" in lowered
        and "flashlight" in lowered
    ):
        return False

    unsafe_phrases = [
        "look directly at the sun",
        "stare at the sun",
        "climb a tree",
        "approach a stranger",
        "taste the plant",
        "eat unknown plants",
        "touch unknown insects",
        "go near traffic",
    ]

    if any(phrase in lowered for phrase in unsafe_phrases):
        return False

    category_terms = CATEGORY_KEYWORDS.get(category, [])

    if not any(term in lowered for term in category_terms):
        return False

    # Require three distinct question lines.
    questions = []

    for number in (1, 2, 3):
        match = re.search(
            rf"Question {number}:\s*(.+)",
            quest,
            flags=re.IGNORECASE,
        )

        if not match:
            return False

        question_text = match.group(1).strip()

        if len(question_text) < 10:
            return False

        questions.append(question_text.lower())

    if len(set(questions)) != 3:
        return False

    return True


# ==========================================
# SAFE QUEST FALLBACKS
# ==========================================

def make_fallback_quest(category):
    fallbacks = {
        "🌿 Nature": """
Quest Title: Compare Two Fallen Leaves

What to Do:
1. Find two fallen leaves in a safe, familiar place.
2. Compare their shapes, edges, sizes, and colors.
3. Draw the leaves or write down two differences.
4. Leave living plants undamaged.

Question 1: What differences can you observe between the two leaves?

Question 2: Which feature is easiest to compare, and why?

Question 3: What else would you like to discover about fallen leaves?

Safety Reminders:
Stay in a safe area and ask an adult for help when needed.
Do not taste plants or touch unknown insects.
""",
        "🌙 Astronomy": """
Quest Title: Record the Evening Sky

What to Do:
1. With a trusted adult, observe the sky from a safe place.
2. Notice its colors and whether clouds are visible.
3. Draw what you see or write three details.
4. Never look directly at the Sun.

Question 1: What colors can you observe in the sky?

Question 2: Which parts of the sky look different from each other?

Question 3: What would you like to observe about the sky tomorrow?

Safety Reminders:
Stay in a familiar place with an adult when needed.
Never look directly at the Sun.
""",
        "🔬 Science": """
Quest Title: Compare Two Shadows

What to Do:
1. With an adult, choose two safe objects that cast shadows.
2. Observe their shadows on the ground in the same natural light.
3. Compare the shadows' lengths and shapes.
4. Do not look directly at the Sun.

Question 1: What differences do you notice between the shadows?

Question 2: Which shadow looks longer or shorter?

Question 3: What could you observe later to see whether the shadows change?

Safety Reminders:
Stay in a safe, familiar area.
Never look directly at the Sun.
""",
        "🗺️ Exploration": """
Quest Title: Find Three Shapes Nearby

What to Do:
1. In a safe, familiar place, look for three different shapes.
2. Observe objects without touching anything unsafe.
3. Draw the shapes or describe where you found them.

Question 1: Which three shapes did you notice?

Question 2: Where did you find each shape?

Question 3: What other shapes might be hiding in your surroundings?

Safety Reminders:
Stay away from roads and unfamiliar places.
Ask a trusted adult for help when needed.
""",
        "🎨 Creativity": """
Quest Title: Create a Picture from Five Shapes

What to Do:
1. Find a safe place to sit outdoors or near a window.
2. Draw five simple shapes on paper.
3. Combine them into a picture of something imaginary or familiar.
4. Give your picture a title.

Question 1: Which five shapes did you use?

Question 2: How did you combine them to make your picture?

Question 3: What could you change to create a different picture?

Safety Reminders:
Use safe drawing materials.
Stay in a safe place and ask an adult for help when needed.
""",
    }

    return fallbacks.get(category, fallbacks["🔬 Science"]).strip()


# ==========================================
# QUEST GENERATION
# ==========================================

def generate_quest(category):
    previous_quests = st.session_state.quest_history[-15:]
    previous_titles = []

    for item in previous_quests:
        if isinstance(item, dict):
            title = item.get("title", "")
        else:
            title = get_quest_title(str(item))

        if title:
            previous_titles.append(f"- {title}")

    history_text = "\n".join(previous_titles) or "- None"

    prompt = f"""
You are GetOut, a careful quest designer for children.

Create ONE safe, practical, scientifically sensible real-world quest.

SELECTED CATEGORY: {category}

Category guidelines:
- Nature: fallen leaves, trees, flowers, birds, or natural patterns.
- Astronomy: sky, Moon, or stars observed safely.
- Science: shadows, sound, motion, light, water, or balance.
- Exploration: familiar surroundings, landmarks, shapes, or directions.
- Creativity: drawing, sketching, patterns, or storytelling.

Strict requirements:
- Write the entire response in English using Latin letters.
- The activity must be possible in a safe, familiar place.
- Do not invent scientific facts or misleading instructions.
- Do not ask a child to use a flashlight to compare sunny and shaded areas.
  Compare those areas directly using natural daylight.
- Never ask a child to look directly at the Sun.
- Never suggest touching unknown plants or insects, tasting outdoor objects,
  climbing, approaching strangers, entering isolated places, or going near traffic.
- Do not damage living plants.
- Do not require special equipment or spending money.
- Avoid repeating previous quest titles or making slightly renamed copies.
- Make each question different:
  Question 1 asks about a direct observation.
  Question 2 asks for a comparison or another detail.
  Question 3 asks what the child is curious about next.
- Do not repeat the same question in different words.

Previous quest titles:
{history_text}

Use exactly this format:

Quest Title:
What to Do:
1.
2.
3.

Question 1:
Question 2:
Question 3:

Safety Reminders:
- Add two or three relevant safety reminders.

Do not include an introduction or extra sections.
"""

    try:
        response = ollama.chat(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.4},
        )

        quest = response["message"]["content"].strip()

        if validate_quest(quest, category):
            return quest

    except Exception:
        pass

    return make_fallback_quest(category)


# ==========================================
# MENTOR FEEDBACK
# ==========================================

def make_fallback_feedback(quest, observation):
    lowered = quest.lower()
    title = get_quest_title(quest)

    if "shadow" in lowered:
        follow_up = (
            "Next time, compare the two shadows' lengths and shapes "
            "from the same place. What difference can you actually see?"
        )
    elif "sunny area" in lowered or "shaded area" in lowered:
        follow_up = (
            "Next time, compare both areas directly in natural daylight. "
            "Which area looks brighter to you?"
        )
    elif "leaf" in lowered:
        follow_up = (
            "Next time, compare the leaves' edges, shapes, or sizes. "
            "Which difference is easiest to notice?"
        )
    elif "sky" in lowered or "moon" in lowered or "star" in lowered:
        follow_up = (
            "What is one more detail you could observe about the sky "
            "without looking directly at the Sun?"
        )
    else:
        follow_up = (
            "What is one more detail you could observe, compare, or record "
            "the next time you try this activity?"
        )

    safe_observation = observation.strip().replace('"', "'")[:500]

    return f"""
### 1. What you reported

You wrote: "{safe_observation}"

I can use the details you shared, but I cannot independently verify what happened.
For "{title}", try to record exactly what you saw or did.

### 2. Think about it

Your notes are a starting point. Add one specific detail, such as a visible
difference, a shape, a direction, or a comparison that matches the activity.
Avoid guessing at a cause before collecting more observations.

### 3. Explore further

{follow_up}

**Curiosity score: 5/10.** You shared an observation. Adding one or two
specific details would make it easier to investigate.
""".strip()


def validate_feedback(feedback):
    if not feedback or len(feedback) < 80 or len(feedback) > 1800:
        return False

    if not is_english_script(feedback):
        return False

    lowered = feedback.lower()

    required_sections = [
        "what you reported",
        "think about it",
        "explore further",
        "curiosity score",
    ]

    return all(section in lowered for section in required_sections)


def generate_mentor_feedback(quest, observation):
    prompt = f"""
You are a careful, supportive learning mentor for a child.

QUEST:
{quest}

CHILD'S EXACT OBSERVATION:
{observation}

Your job is to help the child think, not invent what happened.

Rules:
- Write only in English using Latin letters.
- Refer only to details explicitly present in the child's observation.
- Do not claim the child saw, measured, touched, or tested something
  unless the child explicitly said so.
- Do not invent object properties, measurements, events, or causes.
- Do not assume why something happened.
- If the observation is vague, identify one specific missing detail.
- Make feedback relevant to the actual quest.
- Ask one simple, useful follow-up question.
- Do not give a made-up scientific explanation.
- Keep the response short, kind, and child-friendly.

Use exactly these headings:

### 1. What you reported
Briefly reflect what the child actually wrote.

### 2. Think about it
Identify one relevant detail that is missing or one comparison the child could make.

### 3. Explore further
Ask one clear question that can be answered by further observation.

Finish with:
**Curiosity score: X/10.** Give a brief reason based only on the observation.
Use a score from 1 to 10. Do not judge the child as a person.
"""

    try:
        response = ollama.chat(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.2},
        )

        feedback = response["message"]["content"].strip()

        if validate_feedback(feedback):
            return feedback

    except Exception:
        pass

    return make_fallback_feedback(quest, observation)


# ==========================================
# HISTORY HELPERS
# ==========================================

def history_title(item):
    if isinstance(item, dict):
        return item.get("title") or get_quest_title(item.get("quest", ""))

    return get_quest_title(str(item))


def history_category(item):
    if isinstance(item, dict):
        return item.get("category", "Not recorded")

    return "Not recorded"


def history_date(item):
    if isinstance(item, dict):
        return item.get("date", "Not recorded")

    return "Not recorded"


def history_gems(item):
    if isinstance(item, dict):
        return item.get("gems_earned", 0)

    return 0


def count_categories(history):
    counts = {category: 0 for category in CATEGORIES}

    for item in history:
        category = history_category(item)

        if category in counts:
            counts[category] += 1

    return counts


def add_quest_to_history(quest, category):
    # Keep the current quest in history without deleting old records.
    st.session_state.quest_history.insert(
        0,
        {
            "title": get_quest_title(quest),
            "quest": quest,
            "category": category,
            "date": date.today().isoformat(),
            "gems_earned": 0,
        },
    )


def update_current_history_reward(gems_earned):
    current_title = get_quest_title(st.session_state.ai_quest)
    today_string = date.today().isoformat()

    for item in st.session_state.quest_history:
        if (
            isinstance(item, dict)
            and item.get("title") == current_title
            and item.get("date") == today_string
        ):
            item["gems_earned"] = gems_earned
            return


# ==========================================
# INITIALIZE SESSION STATE
# ==========================================

if "progress_loaded" not in st.session_state:
    saved = load_progress()

    st.session_state.gems = saved["gems"]
    st.session_state.streak = saved["streak"]
    st.session_state.badges = saved["badges"]
    st.session_state.last_completed_date = parse_saved_date(
        saved["last_completed_date"]
    )
    st.session_state.quest_history = saved["quest_history"]
    st.session_state.ai_quest = saved["daily_quest"]
    st.session_state.quest_date = parse_saved_date(saved["quest_date"])
    st.session_state.quest_category = saved["quest_category"]
    st.session_state.completed_quest_date = parse_saved_date(
        saved["completed_quest_date"]
    )
    st.session_state.daily_feedback = saved["daily_feedback"]
    st.session_state.observation = ""
    st.session_state.progress_loaded = True

session_defaults = {
    "gems": DEFAULT_GEMS,
    "streak": 0,
    "badges": [],
    "last_completed_date": None,
    "quest_history": [],
    "ai_quest": "",
    "quest_date": None,
    "quest_category": None,
    "completed_quest_date": None,
    "daily_feedback": "",
    "observation": "",
}

for key, value in session_defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


today = date.today()

# Expire the previous day's quest without resetting long-term progress.
if st.session_state.quest_date != today:
    st.session_state.ai_quest = ""
    st.session_state.quest_date = None
    st.session_state.quest_category = None
    st.session_state.daily_feedback = ""
    st.session_state.observation = ""


# ==========================================
# PAGE HEADER
# ==========================================

st.title("🌍 GetOut")
st.write("AI-powered real-world adventure for kids")
st.write("Your screen is the starting point. The real adventure is outside!")

col1, col2 = st.columns(2)

with col1:
    st.metric("💎 Gems", st.session_state.gems)

with col2:
    st.metric("🔥 Daily Streak", f"{st.session_state.streak} days")

st.write("🏅 **Badges**")

if st.session_state.badges:
    for badge in st.session_state.badges:
        st.write(f"• {badge}")
else:
    st.write("No badges yet. Complete your first quest!")

st.divider()


# ==========================================
# CATEGORY AND QUEST GENERATION
# ==========================================

category = st.selectbox("Choose your adventure", CATEGORIES)

if st.button("Get Today's Quest", type="primary"):
    same_category_quest_exists = (
        st.session_state.quest_date == today
        and bool(st.session_state.ai_quest)
        and st.session_state.quest_category == category
    )

    if not same_category_quest_exists:
        with st.spinner("Preparing a safe, real-world adventure..."):
            quest = generate_quest(category)

        st.session_state.ai_quest = quest
        st.session_state.quest_date = today
        st.session_state.quest_category = category
        st.session_state.daily_feedback = ""
        st.session_state.observation = ""

        add_quest_to_history(quest, category)
        save_progress()
        st.rerun()


# ==========================================
# DISPLAY AND COMPLETE QUEST
# ==========================================

quest_is_for_today = (
    st.session_state.quest_date == today
    and bool(st.session_state.ai_quest)
)

if quest_is_for_today:
    st.subheader("🤖 Today's AI Quest")
    st.caption(f"Category: {st.session_state.quest_category}")
    st.markdown(st.session_state.ai_quest)

    st.info(
        "🌱 Don't ask AI for the answer. "
        "Go outside, observe, think and learn!"
    )

    if st.session_state.completed_quest_date == today:
        st.success("🎉 You've completed a quest today!")

        if st.session_state.daily_feedback:
            st.subheader("🧠 AI Mentor Feedback")
            st.markdown(st.session_state.daily_feedback)

        st.info(
            "Today's reward was already claimed. "
            "This quest earned no extra Gems."
        )

    else:
        st.subheader("📝 Your Observation")

        with st.form("observation_form"):
            observation = st.text_area(
                "What did you discover?",
                key="observation",
                placeholder="Write what you actually observed or tried...",
            )

            submitted = st.form_submit_button("Complete Quest")

        if submitted:
            if not observation.strip():
                st.warning("Please write what you discovered first.")

            elif st.session_state.completed_quest_date == today:
                st.warning("Today's reward has already been claimed.")

            else:
                with st.spinner("Your AI mentor is reviewing your observation..."):
                    feedback = generate_mentor_feedback(
                        st.session_state.ai_quest,
                        observation.strip(),
                    )

                last_completed = st.session_state.last_completed_date

                # Update the daily streak.
                if last_completed is None:
                    st.session_state.streak = 1

                else:
                    days_passed = (today - last_completed).days

                    if days_passed == 1:
                        st.session_state.streak += 1

                    elif days_passed > 1:
                        st.session_state.streak = 1

                        if st.session_state.gems > 0:
                            st.session_state.gems -= 1

                # Only the first completed quest of the day earns Gems.
                gems_earned = DAILY_REWARD
                st.session_state.gems += gems_earned

                st.session_state.last_completed_date = today
                st.session_state.completed_quest_date = today
                st.session_state.daily_feedback = feedback

                if "🌱 First Adventure" not in st.session_state.badges:
                    st.session_state.badges.append("🌱 First Adventure")

                if (
                    st.session_state.gems >= 20
                    and "🔎 Curious Explorer" not in st.session_state.badges
                ):
                    st.session_state.badges.append("🔎 Curious Explorer")

                update_current_history_reward(gems_earned)

                save_progress()
                st.rerun()


# ==========================================
# HISTORY AND CATEGORY DASHBOARD
# ==========================================

st.divider()
st.header("📚 Your Quest History")

history = st.session_state.quest_history

st.write(f"**Recorded quests:** {len(history)}")

counts = count_categories(history)

st.subheader("📊 Adventures by category")

for category_name in CATEGORIES:
    st.write(f"{category_name}: **{counts[category_name]}**")

unclassified_count = sum(
    1 for item in history
    if history_category(item) == "Not recorded"
)

if unclassified_count:
    st.caption(
        f"{unclassified_count} older quest(s) have no saved category. "
        "Their original categories cannot be recovered automatically."
    )

st.subheader("🗂️ Past adventures")

if not history:
    st.write("No quests recorded yet.")

else:
    for index, item in enumerate(history[:50], start=1):
        title = history_title(item)
        category_name = history_category(item)
        saved_date = history_date(item)
        gems_earned = history_gems(item)

        with st.expander(f"{index}. {title}"):
            st.write(f"**Category:** {category_name}")
            st.write(f"**Date:** {saved_date}")
            st.write(f"**Gems earned:** +{gems_earned}")

            if isinstance(item, dict) and item.get("quest"):
                st.markdown(item["quest"])
            elif isinstance(item, str):
                st.markdown(item)

st.caption(
    "GetOut encourages curiosity, independent thinking, "
    "safe outdoor exploration, and learning beyond screens."
)