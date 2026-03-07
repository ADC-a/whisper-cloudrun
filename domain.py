"""
domain.py  —  Iraqi Arabic normalization and Whisper domain bias.

Loaded once at container startup by main.py.  Per-request calls to
normalize_text() perform only compiled-regex substitutions and set
lookups — no I/O, no model loading, no network calls.

This module does NOT classify categories or detect intent.
Those responsibilities belong to the downstream processing script.
"""
from __future__ import annotations

import re

from numbers_ar_iq import (
    SAFE_NUMBER_CORRECTIONS as _SAFE_NUMBER_CORRECTIONS,
    NUMBER_VARIANTS         as _NUMBER_VARIANTS_RAW,
    NUMBER_VALUES           as _NUMBER_VALUES_RAW,
    PHRASE_DIGIT_PATTERNS   as _PHRASE_DIGIT_PATTERNS_RAW,
)


# ══════════════════════════════════════════════════════════════════════════════
# §1  TEXT NORMALIZATION
# ══════════════════════════════════════════════════════════════════════════════

_DIACRITICS_RE = re.compile(r'[\u064B-\u065F\u0640]')   # harakat + tatweel
_ALEF_TABLE    = str.maketrans('أإآٱ', 'اااا')           # alef variants → ا

# ── Safe Iraqi colloquial substitutions ──────────────────────────────────────
# 1-to-1 meaning, no ambiguity with other domain words.
_COLLOQUIAL: dict[str, str] = {
    'بانزين': 'بنزين',   # fuel (Iraqi spoken form)
    'سمچ':    'سمك',     # fish (Iraqi Gaf letter)
}

# ── Iraqi spoken number forms → canonical written forms ──────────────────────
# Sourced from numbers_ar_iq.NUMBER_VARIANTS (imported above).
# domain.py only holds the compiled regex list; the data lives in numbers_ar_iq.
_NUMBER_VARIANTS: dict[str, str] = _NUMBER_VARIANTS_RAW

# ── Whisper misrendering corrections ─────────────────────────────────────────
# Explicit curated map of words Whisper commonly misrenders for Iraqi Arabic
# expense voice notes.  Each entry is hand-verified to be unambiguous:
# the source form is NOT a valid distinct domain word, so replacing it is safe.
#
# SAFETY RULE: if a source word appears in _PROTECTED_WORDS (below), it will
# NOT be corrected.  This prevents collisions like مركز ↔ ماركت.
_WHISPER_CORRECTIONS: dict[str, str] = {
    # Whisper sometimes renders ماركت with taa marbuta or Persian kaf
    'ماركه':  'ماركت',
    'مارکت':  'ماركت',    # Persian kaf (ک) → Arabic kaf (ك)
    'مارکه':  'ماركت',    # Persian kaf + taa marbuta
    # Common Whisper misrenderings for Iraqi expense words
    'بنذين':  'بنزين',    # ذ→ز confusion
    'كهربا':  'كهرباء',   # truncated hamza
    'كهربه':  'كهرباء',   # taa marbuta instead of hamza
    'انترنيت': 'انترنت',  # extra ya
    'تلفون':  'تلفون',    # keep as-is (identity, safe)
    # Iraqi phonetic rendering of آلاف (thousands)
    # e.g. "ثلاث تلاف" → "ثلاث آلاف" (3000)
    'تلاف':   'آلاف',
}

# ── Pre-compile all substitution patterns at import time ─────────────────────
# All keys are alef-normalized before regex compilation so they match the
# alef-normalized input text.  Sorted longest-first to prevent partial matches.

def _compile_word_subs(d: dict[str, str]) -> list[tuple[re.Pattern, str]]:
    """Compile a dict of (source → replacement) into word-boundary regex pairs.
    Keys are alef-normalized so they match text that has gone through step 2."""
    return [
        (re.compile(r'(?<!\w)' + re.escape(k.translate(_ALEF_TABLE)) + r'(?!\w)'), v)
        for k, v in sorted(d.items(), key=lambda x: -len(x[0]))
    ]

_COLLOQUIAL_SUBS  = _compile_word_subs(_COLLOQUIAL)
_SAFE_NUMBER_SUBS = _compile_word_subs(_SAFE_NUMBER_CORRECTIONS)
_NUMBER_SUBS      = _compile_word_subs(_NUMBER_VARIANTS)
_WHISPER_SUBS     = _compile_word_subs(_WHISPER_CORRECTIONS)

# Phrase-level digit patterns (Whisper multi-word misrecognitions → digits).
# Compiled as-is — patterns already use alef-normalized Arabic.
_PHRASE_DIGIT_SUBS: list[tuple[re.Pattern, str]] = [
    (re.compile(pat, re.UNICODE), rep)
    for pat, rep in _PHRASE_DIGIT_PATTERNS_RAW
]

# ── Number word → digit conversion ───────────────────────────────────────────
# Alef-normalized lookup table: canonical Arabic number words → int values.
# Both the table keys and the runtime tokens go through alef normalization
# so they match reliably.
_NUMBER_VALUES_NORM: dict[str, int] = {
    k.translate(_ALEF_TABLE): v
    for k, v in _NUMBER_VALUES_RAW.items()
}

def _try_read_number(tokens: list[str], start: int) -> tuple[int, int]:
    """Greedily parse a compound Arabic number at tokens[start].

    Returns (value, tokens_consumed).  Returns (0, 0) if no number found.
    Stops at multiplier words (ألف, مليون …) — those stay as Arabic words
    so the downstream parser can handle "11 ألف" (= 11 000) naturally.
    Handles و connector between number words: "ثلاثمئة و عشرين" → 320.
    """
    total   = 0
    j       = start
    in_span = False   # True once we've consumed at least one number word

    while j < len(tokens):
        tok_norm = tokens[j].translate(_ALEF_TABLE)

        # و connector — only skip when already inside a number span
        if tok_norm == 'و' and in_span:
            j += 1
            continue

        # Two-word match (e.g. "سبعة عشر" = 17)
        if j + 1 < len(tokens):
            two = tok_norm + ' ' + tokens[j + 1].translate(_ALEF_TABLE)
            if two in _NUMBER_VALUES_NORM:
                total  += _NUMBER_VALUES_NORM[two]
                j      += 2
                in_span = True
                continue

        # Single-word match
        if tok_norm in _NUMBER_VALUES_NORM:
            total  += _NUMBER_VALUES_NORM[tok_norm]
            j      += 1
            in_span = True
            continue

        break  # not a number word — stop span

    consumed = j - start
    return (total, consumed) if consumed > 0 else (0, 0)


def _words_to_digits(text: str) -> str:
    """Replace canonical Arabic number words with digit strings.

    Multiplier scale words (ألف, مليون, مليار) are left as Arabic so the
    downstream parser can resolve "11 ألف" → 11 000 etc.

    Examples (post NUMBER_VARIANTS):
      "ثلاثين ألف"         → "30 ألف"
      "احد عشر ألف"        → "11 ألف"
      "ثلاثمئة و عشرين"   → "320"
    """
    tokens = text.split()
    result: list[str] = []
    i = 0
    while i < len(tokens):
        value, consumed = _try_read_number(tokens, i)
        if consumed > 0:
            result.append(str(value))
            i += consumed
        else:
            result.append(tokens[i])
            i += 1
    return ' '.join(result)


# ── Post-normalization cosmetic restorations ──────────────────────────────────
# Alef normalization strips hamza from ألف → الف.  Restore the canonical
# written form (ألف = thousand) as a final step so the output is readable.
_ALEF_RESTORE_SUBS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'(?<!\w)الف(?!\w)'),   'ألف'),    # ألف  (singular)
    (re.compile(r'(?<!\w)الاف(?!\w)'),  'آلاف'),   # آلاف (plural)
    (re.compile(r'(?<!\w)الفين(?!\w)'), 'ألفين'),  # ألفين (dual)
]

# ── Punctuation and thousand-separator cleanup ────────────────────────────────
# Applied late in the pipeline so number-word patterns are not disrupted.

# Thousand-dot:  "10.000" → "10000",  "320.000" → "320000"
# Only matches a dot flanked by digit(s) on the left and exactly 3 digits
# followed by a non-digit or end-of-string on the right.
_THOUSAND_DOT_RE = re.compile(r'(?<=\d)\.(?=\d{3}(?:\D|$))')

# Punctuation characters that break downstream parsing.
# Replaced with a space (not deleted) to avoid merging adjacent words.
_PUNCT_RE = re.compile(r'[.,،;!؟]')


# ══════════════════════════════════════════════════════════════════════════════
# §2  VOCABULARY DATA (reference + protected words)
# ══════════════════════════════════════════════════════════════════════════════
# Category keywords are kept here as domain reference material.  They are used
# ONLY to build _PROTECTED_WORDS (preventing unsafe corrections) and to inform
# INITIAL_PROMPT.  No classification or scoring is done in this module.

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
# §3  PROTECTED WORDS SET  (built once at import)
# ══════════════════════════════════════════════════════════════════════════════
# All single words that appear as valid domain vocabulary.  A word in this set
# is NEVER auto-corrected to another word by the Whisper correction step.
# This is the safety mechanism that prevents ماركت ↔ مركز confusion:
# both are protected, so neither gets silently rewritten.

def _build_protected() -> set[str]:
    """Extract all single words from all category keyword lists + triggers."""
    words: set[str] = set()
    for kw_list in _RAW_CATEGORIES.values():
        for phrase in kw_list:
            # Normalize alef before inserting so lookup works after step 2
            normalized = _DIACRITICS_RE.sub('', phrase).translate(_ALEF_TABLE)
            for w in normalized.split():
                if len(w) > 1:   # skip single-char noise
                    words.add(w)
    for trigger_list in (INCOME_TRIGGERS, DEBT_TRIGGERS):
        for phrase in trigger_list:
            normalized = _DIACRITICS_RE.sub('', phrase).translate(_ALEF_TABLE)
            for w in normalized.split():
                if len(w) > 1:
                    words.add(w)
    # Explicitly protect key ambiguous words
    words.add('مركز')
    words.add('ماركت')
    return words

_PROTECTED_WORDS: set[str] = _build_protected()


def normalize_text(text: str) -> str:
    """
    Normalize Iraqi Arabic text for downstream processing.

    Pipeline (order matters):
      1.  Remove diacritics + tatweel.
      2.  Normalize alef variants أإآٱ → ا.
      3.  Insert space after conjunction و glued to the next word.
      4.  Thousand-dot fix:  10.000 → 10000  (before punct strip).
      5.  SAFE_NUMBER_CORRECTIONS:  مير→مية,  ميت→مئة.
      6.  PHRASE_DIGIT_PATTERNS: multi-word Whisper misrecognitions → digits.
      7.  NUMBER_VARIANTS: Iraqi dialect words → canonical Arabic.
      8.  Punctuation removal:  . , ، ; ! ؟  → space.
      9.  Words-to-digits: canonical Arabic number words → digit strings.
             e.g.  "ثلاثين ألف" → "30 ألف",  "سبعة عشر" → "17"
      10. Safe colloquial substitutions: بانزين→بنزين, سمچ→سمك.
      11. Whisper misrendering corrections (protected-word-safe).
      12. Collapse whitespace.

    Intentionally NOT applied:
      • ة/ه and ى/ي normalization — kept as-is so ماركت ≠ مركز.
      • Fuzzy/phonetic matching — only explicit curated corrections.
      • Category classification or intent detection.
    """
    # Step 1-2: diacritics, tatweel, alef variants
    t = _DIACRITICS_RE.sub('', text).translate(_ALEF_TABLE)

    # Step 3: insert space after conjunction و glued to the next word
    # "مليون وميه" → "مليون و ميه" so word-boundary regexes match ميه
    t = re.sub(r'(?<= )و(?=\S)', 'و ', t)

    # Step 4: thousand-dot cleanup  10.000 → 10000
    t = _THOUSAND_DOT_RE.sub('', t)

    # Step 5: safe number corrections (مير→مية, ميت→مئة)
    for pat, rep in _SAFE_NUMBER_SUBS:
        t = pat.sub(rep, t)

    # Step 6: phrase-level digit patterns (multi-word Whisper misrecognitions)
    for pat, rep in _PHRASE_DIGIT_SUBS:
        t = pat.sub(rep, t)

    # Step 7: Iraqi dialect number words → canonical Arabic number words
    for pat, rep in _NUMBER_SUBS:
        t = pat.sub(rep, t)

    # Step 8: punctuation removal — replace with space to avoid word merging
    t = _PUNCT_RE.sub(' ', t)

    # Step 9: canonical Arabic number words → digit strings
    t = _words_to_digits(t)

    # Step 10: safe colloquial substitutions
    for pat, rep in _COLLOQUIAL_SUBS:
        t = pat.sub(rep, t)

    # Step 11: Whisper misrendering corrections (protected-word-safe)
    for pat, rep in _WHISPER_SUBS:
        def _safe_replace(m: re.Match) -> str:
            word = m.group(0)
            if word in _PROTECTED_WORDS:
                return word
            return rep
        t = pat.sub(_safe_replace, t)

    # Step 12: collapse multiple spaces, strip edges
    t = re.sub(r'  +', ' ', t).strip()

    # Step 13: restore ألف hamza (alef normalization stripped it in step 2)
    for pat, rep in _ALEF_RESTORE_SUBS:
        t = pat.sub(rep, t)

    return t


# ══════════════════════════════════════════════════════════════════════════════
# §4  WHISPER INITIAL PROMPT
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
#   • Kept concise (~50 words) to stay within the effective context window.

INITIAL_PROMPT: str = (
    "ماركت، مصرف شخصي، بنزين، دواء، كهرباء، نت، ايجار، دين، سلفة، "
    "مطعم، واجب، هدية، سيارة، ملابس، صالون، جم، سفر، بزنس، تسوق. "
    "ماركت خمسين ألف، بنزين ستين ألف، مصرف شخصي ثلاثين ألف، "
    "دفعت دين مئة ألف، سددت دفعة دين، استلمت مبلغ، انطيت واجب، "
    "عيادة مداخيل مئتين ألف، دخل راتب."
)

# ── Whisper hotwords ──────────────────────────────────────────────────────────
# Passed as hotwords= to model.transcribe().  faster-whisper tokenizes this
# string and prepends the tokens to the decoder prompt for every segment,
# directly biasing beam search toward these token sequences.
#
# Complements initial_prompt (which provides broader text context).
# Hotwords provide per-word logit pressure — most effective for short,
# easily-confused domain terms that a long initial_prompt cannot reliably fix.
#
# Rules:
#   • Use canonical target forms (what we WANT Whisper to output).
#   • Prioritize words with known misrendering history.
#   • Keep it short: the implementation caps at max_length/2 tokens (~224).
#   • Do NOT duplicate large blocks — a focused list outperforms a long dump.
HOTWORDS: str = (
    "ماركت، بنزين، كهرباء، انترنت، إيجار، دين، سلفة، "
    "دواء، صيدلية، مطعم، واجب، هدية، مصرف شخصي، عيادة"
)
