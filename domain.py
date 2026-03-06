"""
domain.py  —  Iraqi Arabic expense domain knowledge for faster-whisper.

All heavy data structures (_INDEX, _PHRASE_KEYS, _AMBIGUOUS_KEYS) are built
once at module import time (triggered by main.py at container startup).

Per-request calls to normalize_text() and resolve_categories() perform only
compiled-regex substitutions and dictionary lookups — no I/O, no model
loading, no network calls.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ══════════════════════════════════════════════════════════════════════════════
# §1  TEXT NORMALIZATION
# ══════════════════════════════════════════════════════════════════════════════

_DIACRITICS_RE = re.compile(r'[\u064B-\u065F\u0640]')   # harakat + tatweel
_ALEF_TABLE    = str.maketrans('أإآٱ', 'اااا')           # alef variants → ا

# Safe Iraqi colloquial substitutions: 1-to-1 meaning, no ambiguity with other categories.
_COLLOQUIAL: dict[str, str] = {
    'بانزين': 'بنزين',   # fuel (Iraqi spoken form)
    'سمچ':    'سمك',     # fish (Iraqi spoken form, Gaf letter)
}

# Iraqi spoken number forms → canonical written forms.
# Used in normalize_text() for human-readable display of the normalised text.
_NUMBER_VARIANTS: dict[str, str] = {
    'تلاثه وعشرين': 'ثلاثة وعشرون',  # longest first to avoid partial match
    'تلاثين':        'ثلاثين',
    'تلثميه':        'ثلاث مئة',
    'اربعميه':       'اربعة مئة',
    'اربعطعش':       'اربعة عشر',
    'خمسطعش':        'خمسة عشر',
    'ثمنطعش':        'ثمانية عشر',
    'سبعطش':         'سبعة عشر',
    'تلطعش':         'ثلاثة عشر',
    'اهدعش':         'احد عشر',
    'سطعش':          'ستة عشر',
    'ثنعش':          'اثنا عشر',
    'الميه':         'مئة',
    'ميه':           'مئة',
}

# Compile substitution patterns once at import time.
# (?<!\w) / (?!\w) used instead of \b for reliable Unicode word boundaries.
_COLLOQUIAL_SUBS = [
    (re.compile(r'(?<!\w)' + re.escape(k) + r'(?!\w)'), v)
    for k, v in sorted(_COLLOQUIAL.items(), key=lambda x: -len(x[0]))
]
_NUMBER_SUBS = [
    (re.compile(r'(?<!\w)' + re.escape(k) + r'(?!\w)'), v)
    for k, v in sorted(_NUMBER_VARIANTS.items(), key=lambda x: -len(x[0]))
]


def normalize_text(text: str) -> str:
    """
    Normalize Iraqi Arabic text for display and downstream category matching.

    Applied transformations:
      • Remove diacritics + tatweel (harakat vary between speakers and ASR).
      • Normalize alef variants أإآٱ → ا (semantically identical).
      • Substitute safe Iraqi colloquial words: بانزين→بنزين, سمچ→سمك.
      • Substitute Iraqi spoken number forms: تلاثين→ثلاثين, ميه→مئة, etc.

    Intentionally NOT applied (to avoid silent category confusion):
      • ة/ه and ى/ي — preserved so ماركت ≠ مركز remains detectable.
      • Fuzzy/phonetic matching across category boundaries.
      • Synonym expansion — handled explicitly in resolve_categories().
    """
    t = _DIACRITICS_RE.sub('', text).translate(_ALEF_TABLE)
    for pat, rep in _COLLOQUIAL_SUBS:
        t = pat.sub(rep, t)
    for pat, rep in _NUMBER_SUBS:
        t = pat.sub(rep, t)
    return t


def _mk(text: str) -> str:
    """
    Match-key: applied to BOTH query and index keys during category lookup.
    More aggressive than normalize_text(): also collapses ة/ه and ى/ي.
    This allows a keyword written as 'صيدلية' to match a transcription
    written as 'صيدليه' (or vice versa) — while still keeping ماركت and
    مركز distinct (they differ on ا/و, not on ة/ه).

    This result is NEVER stored or returned to the caller.
    """
    t = _DIACRITICS_RE.sub('', text).translate(_ALEF_TABLE)
    t = re.sub(r'ة(?=\s|$)', 'ه', t)   # taa marbuta → ha at word-end only
    t = t.replace('ى', 'ي')             # alef maqsura → ya
    return t.strip()


# ══════════════════════════════════════════════════════════════════════════════
# §2  VOCABULARY DATA
# ══════════════════════════════════════════════════════════════════════════════

# Intent triggers — checked before category scoring.
# Matching any of these biases the 'intent' field of the response.
INCOME_TRIGGERS: list[str] = [
    'دخل', 'وارد', 'راتب', 'معاش', 'ايداع', 'إيداع', 'بيع',
    'استرجاع', 'تحصيل', 'مبيعات', 'حواله وارده', 'حوالة واردة',
]
DEBT_TRIGGERS: list[str] = [
    'دين', 'ديون', 'سلفه', 'سلفة', 'استدانه', 'استدانة', 'قرض',
    'قسط', 'اقساط', 'أقساط', 'مطلوب', 'مطلوبلي', 'يطلبني', 'يطلبوني',
    'يطالبني', 'اطلبه', 'اطلبهم', 'داين', 'داينت', 'تداينت',
    'بذمتي', 'بذمته', 'بذمتهم', 'سددت', 'سداد', 'تسديد',
    'دفعة دين', 'دفعه دين',
]

# Categories: each value is a list of keywords.
# Position 0  = canonical name           → weight 2.0 in resolver
# Positions 1-2 = common aliases/names   → weight 1.5
# Remaining     = supporting keywords    → weight 1.0
_RAW_CATEGORIES: dict[str, list[str]] = {

    'personal': [
        'مصرف شخصي', 'شخصي',
    ],

    'market': [
        'ماركت', 'سوبرماركت', 'تسوق',
        'تكان', 'مسواك', 'بقاله', 'بقالة', 'خضروات', 'خيار', 'طماطم', 'بصل',
        'تفاح', 'موز', 'برتقال', 'فواكه', 'خضرة', 'لحم', 'دجاج', 'بيض', 'رز',
        'مواد غذائيه', 'مواد غذائية', 'حليب', 'لبن', 'روب', 'جبن', 'قشطة',
        'خبز', 'صمون', 'تمن', 'طحين', 'سكر', 'شاي', 'قهوة', 'عدس', 'حمص',
        'فاصوليا', 'معكرونة', 'دهن', 'سمنة', 'معجون طماطم', 'دجاج مجمد',
        'توابل', 'ملح', 'فلفل', 'كمون', 'كركم', 'خل', 'كاتشب', 'عديل',
        'جاي', 'چاي', 'جكاير', 'سومر', 'مارلبورو', 'كريف', 'باف', 'دخان',
        'زيت طعام', 'زيت نباتي', 'زيت زيتون', 'سوق',
    ],

    'food_out': [
        'مطعم', 'اكل', 'أكل',
        'سندويج', 'سندويچ', 'بيتزا', 'مشاوي', 'كافيه', 'كوفي', 'برغر',
        'مطاعم', 'شاورما', 'مشروبات', 'دليفري', 'صاج', 'لفة', 'كص', 'فلافل',
        'همبركر', 'برياني', 'تكة', 'كباب', 'صحن مشكل', 'مقبلات', 'ثوم',
        'طرشي', 'صمون حار', 'تمن احمر', 'مرق', 'شوربة', 'قوزي', 'سمك مسكوف',
        'سلطة', 'كولا', 'بيبسي', 'عصير',
    ],

    'car': [
        'سيارة', 'تصليح سيارة', 'ميكانيك',
        'الطارات', 'اطارات', 'غسيل سيارة', 'بنجر', 'عجلات', 'بنشر',
        'بريكات', 'قير', 'محرك', 'قشاط تايمينغ', 'فلتر زيت', 'فلتر هواء',
        'راديتر', 'دعامية', 'صبغ سيارة', 'تلميع', 'غسل سيارة', 'تبديل زيت',
        'بطارية سيارة', 'داينمو', 'مباين', 'طايرات', 'جنط', 'ترسيم',
        'فحص كمبيوتر سيارة', 'عادم', 'قفل مركزي', 'زجاج كهرباء',
        'سنوية', 'زيت محرك', 'زيت السيارة', 'زيت موتور',
    ],

    'fuel': [
        'بنزين', 'وقود', 'كازية',
        'ديزل', 'كاو', 'كاز', 'مشتقات', 'مشتقات نفطية', 'شحم', 'تنكة',
        'محطة وقود',
    ],

    'electricity': [
        'كهرباء', 'فاتورة كهرباء', 'اشتراك مولد',
        'ايجار مولد', 'إيجار مولد', 'مولد', 'مولدة', 'مولده',
        'امبير', 'أمبير', 'امبيرات', 'أمبيرات', 'خط كهرباء', 'سحب كهرباء',
    ],

    'internet': [
        'انترنت', 'واي فاي', 'اشتراك نت',
        'اشتراك انترنت', 'نت', 'شحن نت', 'باقات', 'راوتر', 'فايبر',
        'كارت شحن نت', 'اتصالات', 'زين', 'آسيا سيل', 'كورك',
        'تفعيل باقة', 'مودم',
    ],

    'rent': [
        'ايجار', 'إيجار', 'بدل ايجار',
        'اجار', 'أجار', 'بدل إيجار', 'للايجار', 'لايجار', 'شقة',
        'إيجار عيادة', 'إيجار مكتب', 'عقد إيجار',
    ],

    'beauty': [
        'صالون', 'حلاقة', 'قص شعر',
        'صالون نسائي', 'صالون رجالي', 'حلاق', 'حلاقة شعر', 'استشوار',
        'صبغ شعر', 'ميش', 'حنة', 'بدكير', 'منكير', 'مانيكير', 'مساج',
        'شمع', 'واكس', 'تنظيف وجه', 'عناية بشرة', 'عطر', 'عطور',
        'مكياج', 'ميك اب', 'كيراتين', 'بوتوكس شعر',
    ],

    'health': [
        'دواء', 'صيدلية', 'علاج',
        'صيدليه', 'طبيب', 'عيادة', 'عياده', 'تقويم', 'زرع', 'حشوة',
        'تحاليل', 'عملية', 'فحص', 'روشتة', 'مضاد حيوي', 'مسكن',
        'قطرة', 'شراب دواء', 'حقن', 'فيتامين', 'مكمل', 'ضغط دم', 'زكام',
    ],

    'clinic': [
        'عيادة', 'عياده', 'كلينك',
        'العيادة', 'العياده', 'clinic', 'adc',
    ],

    'business': [
        'بزنس', 'مشروع', 'تجارة',
        'عمل', 'شغل', 'تجاره', 'استثمار', 'شركة', 'شركه', 'كورس', 'دوره',
    ],

    'clothes': [
        'ملابس', 'قميص', 'بنطلون',
        'بنطرون', 'تيشيرت', 'حذاء', 'جاكيت', 'عباية', 'بدلة', 'تنورة',
        'ثوب', 'حجاب', 'فستان', 'جزمة', 'نعال', 'كوت', 'شراب جوارب',
        'قبعة', 'حزام', 'ملابس رياضية', 'بيجامة', 'ملابس داخلية',
        'دشداشة', 'يشماغ', 'جينز', 'قماش', 'معطف', 'هودي',
    ],

    'debt': [
        'دين', 'سلفة', 'قسط',
        'ديون', 'سلفه', 'استدانة', 'استدانه', 'قرض', 'اقساط', 'أقساط',
        'سداد', 'تسديد', 'دفعة دين', 'دفعه دين',
    ],

    'electronics': [
        'موبايل', 'كمبيوتر', 'لابتوب',
        'جهاز', 'حاسبة', 'تلفزيون', 'شاحن', 'سماعات', 'اجهزة', 'تابلت',
        'الكترونيات', 'ايفون', 'سامسونگ', 'شاومي', 'كيبل', 'كفر', 'شاشة',
        'كاميرا', 'HDD', 'SSD', 'ذاكرة', 'فلاش', 'كيبورد', 'ماوس',
        'باور بانك', 'سبيكر', 'بلوتوث', 'ريموت', 'فون',
    ],

    'appliances': [
        'ثلاجة', 'غسالة', 'مكيف',
        'ثلاجه', 'فريزر', 'جلاية', 'مبردة', 'شفاط', 'فرن', 'مايكرويف',
        'خلاط', 'عصارة', 'مكنسة', 'سرير', 'مرتبة', 'خزانة', 'كنبة',
        'طاولة', 'كرسي', 'سفرة', 'بساط', 'سجادة', 'مفرش', 'ستائر',
        'نجفة', 'لمبات',
    ],

    'tools': [
        'اسمنت', 'حديد', 'سيراميك',
        'رمل', 'حصى', 'بلوك', 'طابوق', 'أنابيب', 'PVC', 'حنفية', 'سباك',
        'سيفون', 'مطرقة', 'منشار', 'دريل', 'مسامير', 'براغي', 'غراء',
        'اسلاك', 'دهان',
    ],

    'utilities': [
        'كهرباء وطنية', 'فاتورة هاتف', 'سحب صراف',
        'ماء إسالة', 'رسوم تحويل', 'غرامة تأخير', 'رسوم خدمة',
        'اشتراك قنوات',
    ],

    'education': [
        'قرطاسية', 'مدرسة', 'جامعة',
        'دفتر', 'قلم', 'كتب مدرسية', 'منهج', 'درس خصوصي', 'دورة تعليمية',
        'معهد', 'رسوم مدرسية', 'رسوم جامعية', 'قسط مدرسة', 'قسط جامعة',
        'كورس', 'طباعة', 'ملازم',
    ],

    'government': [
        'بطاقة وطنية', 'جواز سفر', 'استمارة',
        'هوية أحوال', 'إخراج قيد', 'كاتب عدل', 'تصديق', 'طابع',
        'ترسيم سيارة', 'فحص فني', 'رسوم بلدية', 'سجل تجاري', 'وكالة',
    ],

    'gift': [
        'هدية', 'هديه', 'عيدية',
        'تحفة', 'مناسبة',
    ],

    'marketing': [
        'تسويق', 'اعلان', 'إعلان',
        'اعلانات', 'إعلانات', 'حملة', 'اعلان ممول', 'إعلان ممول',
    ],

    'photographer': [
        'مصور', 'تصوير فوتوغرافي', 'فوتوغراف',
    ],

    'transport': [
        'تكسي', 'باص', 'مواصلات',
        'تكتك', 'كوستر', 'دراجة نارية', 'سكوتر', 'تذكرة', 'كروة',
        'أجرة', 'نقل بضائع', 'شاحنة', 'توصيل', 'نقل داخلي', 'سائق',
    ],

    'agriculture': [
        'سماد', 'نخيل', 'دواجن',
        'بذور', 'شتلات', 'ماطور سقي', 'مبيد', 'مضخة', 'محراث', 'جرار',
        'علف', 'تمور', 'بيطرة', 'حصاد',
    ],

    'entertainment': [
        'سينما', 'نتفلكس', 'بلايستيشن',
        'شاهد', 'قنوات', 'اكس بوكس', 'ألعاب', 'كافيه نت', 'أركيلة',
        'معسل', 'بيلياردو', 'بولينغ', 'مول', 'حفلة', 'مسرح', 'مهرجان',
    ],

    'travel': [
        'سفر', 'تذاكر', 'طيران',
        'سياحة', 'سفريه', 'رحلة جوية', 'جواز سفر', 'تأشيرة',
        'تذكرة طيران', 'حجز فندق', 'فيزا', 'تأمين سفر', 'شنطة سفر',
        'جمارك', 'معبر حدودي', 'رحله عمرة', 'مطار',
    ],

    'wajib': [
        'واجب', 'انطيت واجب', 'مجاملات',
        'وجبت', 'اجاني واجب', 'واجبات', 'مناسبات', 'عرس', 'مولود',
    ],

    'children': [
        'حضانه', 'ملابس اطفال', 'حفاضات',
        'العاب اطفال', 'لعبه', 'لعبة', 'عربانة', 'حفاظات', 'ببرونه',
        'رضاعة', 'مهد', 'سيت بيبي', 'دمية', 'مكعبات',
    ],

    'household': [
        'قدور', 'فرشة', 'بطانية',
        'مخدة', 'جادر', 'مفرش', 'سجادة', 'ماطور', 'مروحة', 'مدفأة',
        'غاز', 'إبريق', 'كاسة', 'طباخ', 'مكوى', 'مراية', 'ستارة',
        'صحون', 'ملاعق',
    ],

    'gym': [
        'جم', 'اشتراك جم', 'صالة رياضية',
        'قاعة رياضية', 'قاعه رياضيه', 'رياضه',
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# §3  INDEX BUILDING  (runs once at import)
# ══════════════════════════════════════════════════════════════════════════════

# _INDEX: match-key → [(category, weight)]
# Weight reflects keyword position: canonical(2.0) > alias(1.5) > supporting(1.0)
_INDEX: dict[str, list[tuple[str, float]]] = {}
_PHRASE_KEYS: set[str] = set()   # match-keys that contain spaces (multi-word)

for _cat, _keywords in _RAW_CATEGORIES.items():
    for _i, _kw in enumerate(_keywords):
        _key = _mk(_kw)
        _weight = 2.0 if _i == 0 else (1.5 if _i < 3 else 1.0)
        _INDEX.setdefault(_key, []).append((_cat, _weight))
        if ' ' in _key:
            _PHRASE_KEYS.add(_key)

# Phrases sorted longest-first for greedy left-to-right matching
_SORTED_PHRASES: list[str] = sorted(_PHRASE_KEYS, key=len, reverse=True)

# Keys that appear in more than one category → ambiguous if sole signal
_AMBIGUOUS_KEYS: set[str] = {k for k, v in _INDEX.items() if len(v) > 1}

# Pre-computed intent trigger sets (single-word forms)
_INCOME_KEYS_SINGLE: set[str] = {_mk(t) for t in INCOME_TRIGGERS if ' ' not in t}
_DEBT_KEYS_SINGLE:   set[str] = {_mk(t) for t in DEBT_TRIGGERS   if ' ' not in t}

# Compiled patterns for multi-word intent triggers
_INCOME_PHRASE_PATS: list[re.Pattern] = [
    re.compile(r'(?<!\w)' + re.escape(_mk(t)) + r'(?!\w)')
    for t in INCOME_TRIGGERS if ' ' in t
]
_DEBT_PHRASE_PATS: list[re.Pattern] = [
    re.compile(r'(?<!\w)' + re.escape(_mk(t)) + r'(?!\w)')
    for t in DEBT_TRIGGERS if ' ' in t
]


# ══════════════════════════════════════════════════════════════════════════════
# §4  CATEGORY RESOLVER
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class _Score:
    category: str
    score:    float = 0.0
    keywords: list[str] = field(default_factory=list)


def resolve_categories(
    text: str,
    *,
    min_confidence: float = 0.20,
) -> dict:
    """
    Resolve expense categories from (already normalized) Arabic text.

    Parameters
    ----------
    text : str
        The text to resolve — pass the output of normalize_text() for best results,
        or raw transcribed text (normalize_text() is applied internally too).
    min_confidence : float
        Candidates below this score are excluded from category_candidates.

    Returns
    -------
    dict with keys:
        resolved_category   str | None   top category if confidence is sufficient
        resolved_categories list[str]    same as resolved_category wrapped in list
        category_confidence float        0.0–1.0, normalised share of total score
        category_candidates list[dict]   candidates above min_confidence
        is_ambiguous        bool         True when top-two scores are too close
        intent              str | None   "income" | "debt" | None
        warnings            list[str]
        notes               str
    """
    # Apply normalization then match-key transform for internal lookup
    mk_text = _mk(normalize_text(text))
    words   = mk_text.split()
    word_set = set(words)

    warnings:    list[str] = []
    notes_parts: list[str] = []

    # ── Intent detection ─────────────────────────────────────────────────────
    intent: Optional[str] = None
    if word_set & _INCOME_KEYS_SINGLE or any(p.search(mk_text) for p in _INCOME_PHRASE_PATS):
        intent = 'income'
    elif word_set & _DEBT_KEYS_SINGLE or any(p.search(mk_text) for p in _DEBT_PHRASE_PATS):
        intent = 'debt'

    # ── Score accumulation ───────────────────────────────────────────────────
    scores: dict[str, _Score] = {}
    consumed = mk_text  # we remove matched phrases to avoid double-counting

    # 1. Multi-word phrases (greedy, longest first)
    for phrase in _SORTED_PHRASES:
        if phrase in consumed:
            for cat, weight in _INDEX[phrase]:
                s = scores.setdefault(cat, _Score(cat))
                s.score    += weight * 1.5   # phrase match bonus
                s.keywords.append(phrase)
            consumed = consumed.replace(phrase, ' ', 1)

    # 2. Single-word tokens from whatever wasn't consumed by phrases
    for word in consumed.split():
        if word in _INDEX:
            for cat, weight in _INDEX[word]:
                s = scores.setdefault(cat, _Score(cat))
                s.score    += weight
                s.keywords.append(word)

    # ── No matches ───────────────────────────────────────────────────────────
    if not scores:
        return {
            'resolved_category':   None,
            'resolved_categories': [],
            'category_confidence': 0.0,
            'category_candidates': [],
            'is_ambiguous':        False,
            'intent':              intent,
            'warnings':            ['No category keywords found in text'],
            'notes':               'Unresolved — no matching vocabulary',
        }

    # ── Normalise scores to fractional shares ────────────────────────────────
    ranked = sorted(scores.values(), key=lambda c: c.score, reverse=True)
    total  = sum(c.score for c in ranked)
    for c in ranked:
        c.score = round(c.score / total, 3)

    top    = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None

    # ── Ambiguity check ──────────────────────────────────────────────────────
    is_ambiguous = False
    if second and second.score > 0.0:
        gap = top.score - second.score
        if gap < 0.20:
            is_ambiguous = True
            warnings.append(
                f"Ambiguous: '{top.category}' ({top.score:.2f}) vs "
                f"'{second.category}' ({second.score:.2f}) — gap={gap:.2f}"
            )

    # Warn if the only signals are words that appear in multiple categories
    if top.keywords and all(_mk(kw) in _AMBIGUOUS_KEYS for kw in top.keywords):
        is_ambiguous = True
        warnings.append(
            f"All matched keywords for '{top.category}' are cross-category — "
            "confidence may be misleading"
        )

    # ── Resolution decision ───────────────────────────────────────────────────
    resolved: Optional[str] = None
    confidence = top.score

    if confidence >= 0.50 and not is_ambiguous:
        resolved = top.category
        notes_parts.append(f"Resolved: '{resolved}' (conf={confidence:.2f})")
    elif confidence >= 0.35:
        resolved = top.category
        notes_parts.append(f"Tentative: '{resolved}' (conf={confidence:.2f})")
        if not is_ambiguous:
            warnings.append(f"Low confidence for '{resolved}' — review recommended")
    else:
        notes_parts.append(f"Not resolved (top conf={confidence:.2f} < 0.35)")
        warnings.append("Category confidence too low — not resolved")

    # ── Build response ────────────────────────────────────────────────────────
    candidates = [
        {
            'category':         c.category,
            'confidence':       c.score,
            # deduplicate while preserving order
            'matched_keywords': list(dict.fromkeys(c.keywords)),
        }
        for c in ranked
        if c.score >= min_confidence
    ]

    return {
        'resolved_category':   resolved,
        'resolved_categories': [resolved] if resolved else [],
        'category_confidence': confidence,
        'category_candidates': candidates,
        'is_ambiguous':        is_ambiguous,
        'intent':              intent,
        'warnings':            warnings,
        'notes':               '; '.join(notes_parts) if notes_parts else 'OK',
    }


# ══════════════════════════════════════════════════════════════════════════════
# §5  WHISPER INITIAL PROMPT
# ══════════════════════════════════════════════════════════════════════════════
# Passed as initial_prompt to model.transcribe() on every request.
# Biases the decoder toward domain vocabulary without forcing output.
#
# Design rationale:
#   • Canonical category names listed first — Whisper's decoder will prefer
#     these exact forms when the audio is ambiguous.
#   • "ماركت" appears explicitly (not مركز) so Whisper learns the expected
#     form; this is the primary guard against the ماركت/مركز confusion.
#   • Iraqi amount formats (خمسين ألف, مئة ألف) teach the number style.
#   • Short representative phrases match the speaking style of expense notes.
#   • Kept under ~200 words to stay within the effective context window.

INITIAL_PROMPT: str = (
    "ماركت، مصرف شخصي، بنزين، دواء، كهرباء، نت، ايجار، دين، سلفة، "
    "مطعم، واجب، هدية، سيارة، ملابس، صالون، جم، سفر، بزنس، تسوق. "
    "ماركت خمسين ألف، بنزين ستين ألف، مصرف شخصي ثلاثين ألف، "
    "دفعت دين مئة ألف، سددت دفعة دين، استلمت مبلغ، انطيت واجب، "
    "عيادة مداخيل مئتين ألف، دخل راتب."
)
