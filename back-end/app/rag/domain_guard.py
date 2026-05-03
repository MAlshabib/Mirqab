"""
Domain guard and query router for the Mirqab RAG assistant.

Classifies each user question into one of five routes BEFORE the LLM is called,
enforcing hard refusals for out-of-domain and tactical requests.
"""
import re
from enum import Enum


class Route(str, Enum):
    OUT_OF_DOMAIN      = "OUT_OF_DOMAIN"
    UNSAFE_TACTICAL    = "UNSAFE_TACTICAL"
    DATABASE_ANALYTICS = "DATABASE_ANALYTICS"
    RAG_KNOWLEDGE      = "RAG_KNOWLEDGE"
    HYBRID             = "HYBRID"


OUT_OF_DOMAIN_REFUSAL = (
    "أنا مساعد Mirqab فقط، وأقدر أساعدك في الإنذارات، العقد، "
    "وحدات الرؤية والصوت، التقارير، أو بيانات النظام. "
    "هذا السؤال خارج نطاق Mirqab."
)

UNSAFE_TACTICAL_REFUSAL = (
    "لا يمكنني تقديم نصائح تكتيكية أو عسكرية أو إرشادات اعتراض.\n\n"
    "يمكنني مساعدتك في:\n"
    "• شرح الأدلة والبيانات المتاحة للتنبيه الحالي\n"
    "• إعداد ملخص بلاغ محايد للجهة المختصة\n"
    "• عرض سجلات المستشعرات ذات الصلة\n"
    "• التوصية بالتصعيد إلى الضباط المخوّلين\n\n"
    "القرار التشغيلي النهائي يعود للضباط المخوّلين فقط."
)

# ── Injection / prompt-override patterns ─────────────────────────────────────

_INJECTION_PATTERNS = [
    r"انسى\s+كل",
    r"تجاهل.*تعليم",
    r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+instruct",
    r"forget\s+(all\s+)?instruct",
    r"تصرف\s+(كأنك|وكأنك)",
    r"pretend\s+(you\s+are|to\s+be)",
    r"you\s+are\s+now\s+",
    r"jailbreak",
    r"جاوب\s+بدون\s+قيود",
    r"بدون\s+قيود",
    r"without\s+restrictions",
    r"no\s+restrictions",
    r"developer\s+mode",
    r"وضع\s+المطور",
    r"DAN\s*mode",
    r"علمني\s+(كيف\s+)?(اسوي|أسوي|اصنع|أصنع|اعمل|أعمل|تعمل)\s+",
    r"كيف\s+(اسوي|أسوي|اصنع|أصنع)\s+(?!.*(?:إنذار|تنبيه|تقرير|مرقاب))",
]

# ── Out-of-domain topic keywords ──────────────────────────────────────────────

_OUT_OF_DOMAIN_KEYWORDS = [
    # Food
    "كيكة", "وصفة", "طبخ", "طعام", "مطعم", "وجبة",
    "recipe", "cooking", "food", "cake", "bake", "restaurant",
    # Jokes / entertainment
    "نكتة", "نكت", "اضحك", "joke", "funny", "humor",
    "فيلم", "مسلسل", "أغنية", "موسيقى",
    "movie", "series", "song", "music",
    # Personal / social
    "حبيبتي", "حبيبي", "صاحبي", "علاقة حب",
    # Politics
    "انتخاب", "حكومة", "رئيس وزراء", "برلمان",
    "election", "parliament", "prime minister",
    # Sports
    "كرة قدم", "دوري", "رياضة",
    "football", "soccer", "basketball",
]

# ── Tactical / military intercept keywords ────────────────────────────────────

_TACTICAL_KEYWORDS = [
    # Arabic
    "اعترض", "أعترض", "كيف نعترض", "كيف نسقط", "نسقطه",
    "استهدف", "استهداف", "هجوم", "رد نار", "أطلق النار",
    "إسقاط الطائرة", "وجه الدفاع", "وين نوجه", "أين نوجه",
    "نوجه الدفاعات", "تدمير", "إطلاق نار", "مسار الاعتراض",
    "أفضل مكان للاشتباك", "كيف نتصدى", "نتصدى للدرون",
    "أسقط", "تصدٍّ", "صاروخ", "منظومة دفاع",
    # English
    "intercept the drone", "shoot down", "take down", "how to intercept",
    "target the uav", "engage the drone", "fire at", "destroy the",
    "weapon system", "launch strike", "where to aim", "neutralize the",
    "best position to engage", "interception route", "defensive fire",
]

# ── Database analytics trigger keywords ──────────────────────────────────────

_DB_KEYWORDS = [
    "كم تهديد", "كم إنذار", "كم تنبيه", "كم كشف", "كم تم كشف",
    "كم عقدة", "كم نود", "كم وحدة",
    "عدد التهديدات", "عدد الإنذارات", "عدد التنبيهات",
    "إحصائيات اليوم", "إحصاء اليوم",
    "نسبة", "نسبة الخطورة", "توزيع الخطورة", "توزيع التهديدات", "مقارنة بالبقية",
    "أخطر إنذار", "أعلى ثقة", "أكثر إنذارات",
    "حالة العقد", "حالة الوحدات",
    "ملخص اليوم", "ملخص الإنذارات", "ملخص التهديدات",
    "كم وحدة offline", "كم عقدة offline",
    "وحدات offline", "عقد offline",
    "قارن بين إنذارات",
    "قارن بين وحدات",
    "مقارنة بين وحدات",
    "how many threat", "how many alert", "how many detect",
    "how many node", "count of alert", "total threat", "total alert",
    "nodes offline", "nodes online", "node status",
    "daily summary", "today's summary", "stats today",
    "severity ratio", "severity distribution", "alert distribution",
    "worst alert", "highest confidence",
]

# ── Hybrid: needs both DB stats + RAG policy docs ─────────────────────────────

_HYBRID_PATTERNS = [
    r"بناء\s*ً?\s*على\s+سياسة",
    r"وفق\s+السياسة",
    r"اشرح\s+.*إنذارات\s+اليوم",
    r"فسر\s+.*الإنذارات",
    r"explain\s+.*today.*alert.*polic",
    r"based\s+on.*polic",
    r"اليوم.*بناء\s*ً?\s*على",
]


def _matches_keywords(text: str, keywords: list[str]) -> bool:
    t = text.lower()
    return any(kw in t for kw in keywords)


def _matches_patterns(text: str, patterns: list[str]) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in patterns)


def classify_route(question: str) -> tuple[Route, str | None]:
    """
    Classify the question into a route.
    Returns (Route, refusal_message_or_None).
    If the route requires a hard refusal, the message is set.
    """
    # Priority 1: prompt injection / jailbreak attempts
    if _matches_patterns(question, _INJECTION_PATTERNS):
        return Route.OUT_OF_DOMAIN, OUT_OF_DOMAIN_REFUSAL

    # Priority 2: obviously out-of-domain topics
    if _matches_keywords(question, _OUT_OF_DOMAIN_KEYWORDS):
        return Route.OUT_OF_DOMAIN, OUT_OF_DOMAIN_REFUSAL

    # Priority 3: tactical / military advice requests
    if _matches_keywords(question, _TACTICAL_KEYWORDS):
        return Route.UNSAFE_TACTICAL, UNSAFE_TACTICAL_REFUSAL

    # Priority 4: hybrid (needs both DB + RAG docs)
    if _matches_patterns(question, _HYBRID_PATTERNS):
        return Route.HYBRID, None

    # Priority 5: database analytics (counts, stats, status)
    if _matches_keywords(question, _DB_KEYWORDS):
        return Route.DATABASE_ANALYTICS, None

    # Default: RAG knowledge base lookup
    return Route.RAG_KNOWLEDGE, None
