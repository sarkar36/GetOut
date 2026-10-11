
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
    layout="centered",
)

# ==========================================
# CONFIGURATION
# ==========================================

PROGRESS_FILE = Path("progress.json")
DEFAULT_GEMS = 10
MODEL_NAME = "qwen2.5:1.5b"
DAILY_REWARD = 3
MAX_HISTORY = 200

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
        "petal", "bark", "insect", "outdoor",
    ],
    "🌙 Astronomy": [
        "moon", "star", "planet", "sky", "sunset", "sunrise",
        "constellation", "astronomy", "cloud", "night sky",
    ],
    "🔬 Science": [
        "science", "shadow", "light", "sound", "motion", "water",
        "rolling", "balance", "wind", "drying", "brightness",
        "sunny", "shaded", "temperature", "reflection",
    ],
    "🗺️ Exploration": [
        "explore", "map", "landmark", "direction", "route",
        "surroundings", "nearby", "location", "pattern", "surface",
    ],
    "🎨 Creativity": [
        "draw", "drawing", "sketch", "create", "creative",
        "art", "story", "poem", "color", "colour", "design",
    ],
}


# ==========================================
# PROGRESS STORAGE
# ==========================================

def get_default_progress():
    return {
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


def load_progress():
    defaults = get_default_progress()

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

        # Remove only empty or unusable history entries.
        clean_history = []

        for item in saved["quest_history"]:
            if isinstance(item, str):
                if item.strip() and get_quest_title(item) != "Untitled Quest":
                    clean_history.append(item)

            elif isinstance(item, dict):
                quest_text = str(item.get("quest", "")).strip()
                title = str(item.get("title", "")).strip()

                if not title and quest_text:
                    title = get_quest_title(quest_text)

                if title and title != "Untitled Quest":
                    item["title"] = title
                    clean_history.append(item)

        saved["quest_history"] = clean_history[:MAX_HISTORY]

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
            if st.session_state.last_completed_date else None
        ),
        "quest_history": st.session_state.quest_history[:MAX_HISTORY],
        "daily_quest": st.session_state.ai_quest,
        "quest_date": (
            st.session_state.quest_date.isoformat()
            if st.session_state.quest_date else None
        ),
        "quest_category": st.session_state.quest_category,
        "completed_quest_date": (
            st.session_state.completed_quest_date.isoformat()
            if st.session_state.completed_quest_date else None
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
# TEXT HELPERS AND VALIDATION
# ==========================================

def is_english_script(text):
    for character in text:
        if unicodedata.category(character).startswith("L"):
            name = unicodedata.name(character, "")

            if "LATIN" not in name:
                return False

    return True


def get_quest_title(quest):
    match = re.search(
        r"Quest Title:\s*(.+)",
        quest or "",
        flags=re.IGNORECASE,
    )

    if match:
        return match.group(1).strip().strip("*# ")

    return "Untitled Quest"


def normalize_title(title):
    title = unicodedata.normalize("NFKC", title).lower()
    return re.sub(r"[^a-z0-9]+", " ", title).strip()


def titles_are_similar(first, second):
    a = normalize_title(first)
    b = normalize_title(second)

    if not a or not b:
        return False

    if a == b:
        return True

    words_a = set(a.split())
    words_b = set(b.split())

    if not words_a or not words_b:
        return False

    overlap = len(words_a & words_b) / len(words_a | words_b)

    # Catch titles that differ only by a small wording change.
    return overlap >= 0.75


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
        "Safety Reminders:",
    ]

    lowered = quest.lower()

    if not all(section.lower() in lowered for section in required_sections):
        return False

    title = get_quest_title(quest)

    if title == "Untitled Quest" or not 5 <= len(title) <= 100:
        return False

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
        "enter an abandoned building",
        "enter a restricted area",
    ]

    if any(phrase in lowered for phrase in unsafe_phrases):
        return False

    category_terms = CATEGORY_KEYWORDS.get(category, [])

    if not any(term in lowered for term in category_terms):
        return False

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
# FALLBACK QUESTS
# ==========================================

def make_fallback_quest(category):
    fallbacks = {
        "🌿 Nature": [
            """
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
- Stay in a safe, familiar area.
- Do not taste plants or touch unknown insects.
""",
            """
Quest Title: Observe a Plant from a Safe Distance

What to Do:
1. Choose a plant you can observe without damaging it.
2. Notice its visible leaves, stem, and overall shape.
3. Draw the plant or write down three visible details.

Question 1: What visible parts can you identify?
Question 2: How do the leaves differ in size or shape?
Question 3: What would you like to learn about this plant?

Safety Reminders:
- Do not pick or taste unknown plants.
- Avoid touching unknown insects.
""",
            """
Quest Title: Find Natural Patterns Nearby

What to Do:
1. Look for natural patterns in fallen leaves or tree bark.
2. Observe repeated lines, shapes, or colors without damaging plants.
3. Draw one pattern you find.

Question 1: What pattern did you notice?
Question 2: Which lines or shapes repeat?
Question 3: Where else might you find a similar natural pattern?

Safety Reminders:
- Stay in a safe, familiar place.
- Leave living plants undamaged.
""",
        ],
        "🌙 Astronomy": [
            """
Quest Title: Record the Evening Sky

What to Do:
1. Observe the sky from a safe, familiar place.
2. Notice its colors and whether clouds are visible.
3. Draw what you see or write three details.

Question 1: What colors can you observe in the sky?
Question 2: Which parts of the sky look different?
Question 3: What would you like to observe about the sky tomorrow?

Safety Reminders:
- Stay in a safe place with an adult when needed.
- Never look directly at the Sun.
""",
            """
Quest Title: Watch Clouds from a Safe Place

What to Do:
1. Find a comfortable place where you can see the sky.
2. Observe the visible clouds without staring at the Sun.
3. Draw one cloud or describe its outline.

Question 1: What shapes do you notice in the clouds?
Question 2: How do two visible clouds differ?
Question 3: What would you like to observe about clouds next?

Safety Reminders:
- Never look directly at the Sun.
- Stay in a safe, familiar place.
""",
        ],
        "🔬 Science": [
            """
Quest Title: Compare Two Shadows

What to Do:
1. Choose two safe objects that cast shadows.
2. Observe their shadows in the same natural light.
3. Compare the shadows' lengths and shapes.

Question 1: What differences do you notice between the shadows?
Question 2: Which shadow looks longer or shorter?
Question 3: What could you observe later to see whether shadows change?

Safety Reminders:
- Stay in a safe, familiar area.
- Never look directly at the Sun.
""",
            """
Quest Title: Test Which Objects Roll

What to Do:
1. Choose two safe, round objects and a flat surface.
2. Gently roll each object across the same short distance.
3. Observe whether their movement looks different.

Question 1: What happened when you rolled each object?
Question 2: Which object moved differently?
Question 3: What other safe object could you compare next?

Safety Reminders:
- Use small, harmless objects.
- Keep the test away from stairs and roads.
""",
        ],
        "🗺️ Exploration": [
            """
Quest Title: Find Three Shapes Nearby

What to Do:
1. In a safe, familiar place, look for three different shapes.
2. Observe objects without touching anything unsafe.
3. Draw the shapes or describe where you found them.

Question 1: Which three shapes did you notice?
Question 2: Where did you find each shape?
Question 3: What other shapes might be in your surroundings?

Safety Reminders:
- Stay away from roads and unfamiliar places.
- Ask a trusted adult for help when needed.
""",
            """
Quest Title: Map a Familiar Small Area

What to Do:
1. Choose a familiar room, yard, or safe outdoor area.
2. Sketch three recognizable objects or landmarks.
3. Show their approximate positions on your simple map.

Question 1: Which landmarks did you include?
Question 2: Where is one landmark in relation to another?
Question 3: What detail would improve your map?

Safety Reminders:
- Do not enter unfamiliar places.
- Do not share your home address publicly.
""",
        ],
        "🎨 Creativity": [
            """
Quest Title: Create a Picture from Five Shapes

What to Do:
1. Find a safe place to sit outdoors or near a window.
2. Draw five simple shapes on paper.
3. Combine them into a picture and give it a title.

Question 1: Which five shapes did you use?
Question 2: How did you combine them into a picture?
Question 3: What could you change to create a different picture?

Safety Reminders:
- Use safe drawing materials.
- Stay in a safe place.
""",
            """
Quest Title: Draw a Pattern from Nature

What to Do:
1. Observe a natural pattern from a safe distance.
2. Draw a repeating pattern inspired by what you noticed.
3. Add your own colors or shapes to the design.

Question 1: What inspired your pattern?
Question 2: Which shapes or lines repeat?
Question 3: How could you change the design to make another pattern?

Safety Reminders:
- Do not damage plants to collect materials.
- Stay in a safe, familiar place.
""",
        ],
    }

    options = fallbacks.get(category, fallbacks["🔬 Science"])
    used_titles = {
        normalize_title(history_title(item))
        for item in st.session_state.get("quest_history", [])
    }

    for quest in options:
        if normalize_title(get_quest_title(quest)) not in used_titles:
            return quest.strip()

    # If all fallback titles were used, choose a valid fallback anyway.
    # This guarantees the app can still provide a quest offline.
    return options[0].strip()


# ==========================================
# QUEST GENERATION
# ==========================================

def get_previous_titles():
    titles = []

    for item in st.session_state.quest_history:
        title = history_title(item)

        if title and title != "Untitled Quest":
            titles.append(title)

    return titles


def generate_quest(category):
    previous_titles = get_previous_titles()
    previous_titles_text = "\n".join(
        f"- {title}" for title in previous_titles[-40:]
    ) or "- None"

    # Try a few times to avoid a repeated title.
    for attempt in range(3):
        prompt = f"""
You are GetOut, a careful quest designer for children.

Create ONE new, safe, practical outdoor-learning quest.

SELECTED CATEGORY: {category}

Category guidelines:
- Nature: fallen leaves, trees, flowers, birds, natural patterns.
- Astronomy: sky, Moon, stars, and clouds observed safely.
- Science: shadows, sound, motion, light, water, balance.
- Exploration: familiar surroundings, maps, shapes, directions.
- Creativity: drawing, sketching, patterns, storytelling.

Requirements:
- Write in English using Latin letters.
- Use a safe, familiar place and free, ordinary materials.
- Never ask children to look directly at the Sun.
- Never suggest climbing, approaching strangers, entering isolated
  places, going near traffic, tasting plants, or touching unknown insects.
- Do not damage living plants.
- Make the quest meaningfully different from previous activities.
- Do not simply rename a previous quest.
- Questions must ask about observation, comparison, and further curiosity.
- Attempt number: {attempt + 1}
- Avoid the previous titles and activities.

Previous quest titles:
{previous_titles_text}

Use exactly this format:

Quest Title: [new title]

What to Do:
1. [step]
2. [step]
3. [step]

Question 1: [observation question]
Question 2: [comparison question]
Question 3: [further curiosity question]

Safety Reminders:
- [safety reminder]
- [safety reminder]

Do not include an introduction or extra sections.
"""

        try:
            response = ollama.chat(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.7 + attempt * 0.1},
            )

            quest = response["message"]["content"].strip()

            if not validate_quest(quest, category):
                continue

            title = get_quest_title(quest)

            repeated = any(
                titles_are_similar(title, previous)
                for previous in previous_titles
            )

            if not repeated:
                return quest

        except Exception:
            break

    return make_fallback_quest(category)


# ==========================================
# MENTOR FEEDBACK
# ==========================================

def make_fallback_feedback(quest, observation):
    lowered = quest.lower()
    title = get_quest_title(quest)

    if "shadow" in lowered:
        follow_up = (
            "Next time, compare the two shadows' lengths and shapes. "
            "What difference can you actually see?"
        )
    elif "leaf" in lowered or "plant" in lowered:
        follow_up = (
            "Next time, compare visible shapes, edges, or sizes. "
            "Which difference is easiest to notice?"
        )
    elif "sky" in lowered or "moon" in lowered or "star" in lowered:
        follow_up = (
            "What is one more detail you could observe about the sky "
            "without looking directly at the Sun?"
        )
    elif "draw" in lowered or "pattern" in lowered:
        follow_up = (
            "What is one part of your drawing or pattern you could change?"
        )
    else:
        follow_up = (
            "What is one more detail you could observe, compare, or record?"
        )

    safe_observation = observation.strip().replace('"', "'")[:500]

    return f"""
### 1. What you reported

You wrote: "{safe_observation}"

I cannot independently verify what happened. For "{title}", record what
you actually saw or tried.

### 2. Think about it

Your notes are a starting point. Add one specific detail, such as a visible
difference, a shape, a direction, or a comparison. Avoid guessing at a cause
before collecting more observations.

### 3. Explore further

{follow_up}

**Curiosity score: 5/10.** You shared an observation. Adding specific details
would make it easier to investigate.
""".strip()


def validate_feedback(feedback):
    if not feedback or len(feedback) < 80 or len(feedback) > 1800:
        return False

    if not is_english_script(feedback):
        return False

    lowered = feedback.lower()

    required = [
        "what you reported",
        "think about it",
        "explore further",
        "curiosity score",
    ]

    return all(section in lowered for section in required)


def generate_mentor_feedback(quest, observation):
    prompt = f"""
You are a supportive learning mentor for a child.

QUEST:
{quest}

CHILD'S EXACT OBSERVATION:
{observation}

Rules:
- Write only in English using Latin letters.
- Refer only to details in the child's observation.
- Never claim the child measured, saw, touched, or tested something
  unless they explicitly said so.
- Do not invent measurements, events, properties, or causes.
- If the observation is vague, identify one missing detail.
- Ask one simple follow-up question.
- Be kind and concise.

Use exactly these headings:

### 1. What you reported
Reflect what the child actually wrote.

### 2. Think about it
Identify one missing detail or useful comparison.

### 3. Explore further
Ask one clear question for further observation.

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
    title = get_quest_title(quest)

    st.session_state.quest_history.insert(
        0,
        {
            "title": title,
            "quest": quest,
            "category": category,
            "date": date.today().isoformat(),
            "gems_earned": 0,
            "completed": False,
            "feedback": "",
        },
    )

    st.session_state.quest_history = (
        st.session_state.quest_history[:MAX_HISTORY]
    )


def update_current_history(gems_earned, completed, feedback):
    today_string = date.today().isoformat()
    current_title = get_quest_title(st.session_state.ai_quest)

    for item in st.session_state.quest_history:
        if (
            isinstance(item, dict)
            and item.get("title") == current_title
            and item.get("date") == today_string
            and item.get("category") == st.session_state.quest_category
        ):
            item["gems_earned"] = gems_earned
            item["completed"] = completed
            item["feedback"] = feedback
            return


# ==========================================
# SESSION INITIALIZATION
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

# Expire yesterday's displayed quest but preserve long-term progress.
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

completed_today = st.session_state.completed_quest_date == today

if completed_today:
    st.info(
        "You have completed today's quest. "
        "Your next quest and reward will be available tomorrow."
    )

if st.button(
    "Get Today's Quest",
    type="primary",
    disabled=completed_today,
):
    if (
        st.session_state.quest_date == today
        and st.session_state.ai_quest
    ):
        st.info("Today's quest is already ready. Try it before generating another.")
    else:
        with st.spinner("Preparing a safe, new adventure..."):
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
        st.success("🎉 You've completed today's quest!")

        if st.session_state.daily_feedback:
            st.subheader("🧠 AI Mentor Feedback")
            st.markdown(st.session_state.daily_feedback)

        st.success(f"You earned {DAILY_REWARD} Gems for today's completion.")
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
            else:
                with st.spinner("Your AI mentor is reviewing your observation..."):
                    feedback = generate_mentor_feedback(
                        st.session_state.ai_quest,
                        observation.strip(),
                    )

                last_completed = st.session_state.last_completed_date

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

                st.session_state.gems += DAILY_REWARD
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

                update_current_history(
                    DAILY_REWARD,
                    True,
                    feedback,
                )

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

            if isinstance(item, dict):
                if item.get("completed"):
                    st.write("**Status:** Completed")

                if item.get("feedback"):
                    st.markdown("**Mentor feedback**")
                    st.markdown(item["feedback"])

                if item.get("quest"):
                    st.markdown(item["quest"])
            elif isinstance(item, str):
                st.markdown(item)

st.caption(
    "GetOut encourages curiosity, independent thinking, "
    "safe outdoor exploration, and learning beyond screens."
)
