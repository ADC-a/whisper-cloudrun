"""
numbers_ar_iq.py — Iraqi Arabic number normalization tables.

Loaded by domain.py at import time.  Contains four public objects:

  1. SAFE_NUMBER_CORRECTIONS  — truly ambiguous spoken forms (مير, ميت).
                                Applied FIRST, before NUMBER_VARIANTS.
  2. NUMBER_VARIANTS          — all Iraqi dialect forms → canonical مئة-based
                                written forms.  Applied second.
  3. NUMBER_VALUES            — canonical word/phrase → integer (100s and below).
  4. MULTIPLIERS              — scale words → integer multiplier (ألف, مليون …).

Normalization pipeline (text-level, no parsing):
    raw text
      → SAFE_NUMBER_CORRECTIONS   (مير → مية,  ميت → مئة)
      → NUMBER_VARIANTS           (مية → مئة,  ثنعش → اثنا عشر, …)
      → canonical Arabic text     (downstream parser uses NUMBER_VALUES + MULTIPLIERS)
"""
from __future__ import annotations

# ── 1. SAFE_NUMBER_CORRECTIONS ────────────────────────────────────────────────
# Words with high collision risk: مير ("emir"), ميت ("dead") are real Arabic
# words.  Applied first so NUMBER_VARIANTS can then canonicalize the output.
#
#   مير  →  مية  →  [NUMBER_VARIANTS]  →  مئة   (100)
#   ميت  →  مئة                                   (100)
SAFE_NUMBER_CORRECTIONS: dict[str, str] = {
    "مير":  "مية",   # Iraqi spoken 100, variant of مية
    "ميت":  "مئة",   # Iraqi spoken 100, variant (also means "dead" in MSA)
}

# ── 2. NUMBER_VARIANTS ────────────────────────────────────────────────────────
# Iraqi dialect / spoken forms → canonical written forms.
# Canonical target for hundreds: compact مئة-suffix (ثلاثمئة, أربعمئة, …).
# domain.py sorts by descending key length before compiling regexes, so
# multi-word forms (e.g. "ثلاث مية") are matched before their sub-words.
NUMBER_VARIANTS: dict[str, str] = {

    # ── Compound phrases (longest first for regex safety) ─────────────────────
    "تلاثه وعشرين":  "ثلاثة وعشرين",
    "تلاثه وعشرون":  "ثلاثة وعشرين",

    # ── A. Units ──────────────────────────────────────────────────────────────
    "وحده":          "واحد",
    "وحدة":          "واحد",
    "اثنينه":        "اثنين",
    "ثنين":          "اثنين",
    "ثنينه":         "اثنين",
    "ثلاثه":         "ثلاثة",
    "تلاثه":         "ثلاثة",
    "اربعه":         "أربعة",
    "خمسه":          "خمسة",
    "سته":           "ستة",
    "سبعه":          "سبعة",
    "ثمانيه":        "ثمانية",
    "تسعه":          "تسعة",
    "عشره":          "عشرة",

    # ── B. Teens 11–19 ────────────────────────────────────────────────────────
    "اهدعش":         "احد عشر",      # 11
    "احدعش":         "احد عشر",      # 11
    "ثنعش":          "اثنا عشر",     # 12
    "اثنعش":         "اثنا عشر",     # 12
    "تلطعش":         "ثلاثة عشر",    # 13
    "ثلاثطعش":       "ثلاثة عشر",    # 13
    "اربعطعش":       "أربعة عشر",    # 14
    "اربعتعش":       "أربعة عشر",    # 14
    "خمستعش":        "خمسة عشر",     # 15
    "خمسطعش":        "خمسة عشر",     # 15
    "مستعش":         "خمسة عشر",     # 15 — dropped initial خ in fast speech
    "ستعش":          "ستة عشر",      # 16
    "سطعش":          "ستة عشر",      # 16
    "سبعتعش":        "سبعة عشر",     # 17
    "سبعطش":         "سبعة عشر",     # 17
    "ثمانطعش":       "ثمانية عشر",   # 18
    "ثمنطعش":        "ثمانية عشر",   # 18
    "تسعتعش":        "تسعة عشر",     # 19
    "تسعطش":         "تسعة عشر",     # 19
    "تسعطعش":        "تسعة عشر",     # 19

    # ── C. Tens ───────────────────────────────────────────────────────────────
    "تلاثين":        "ثلاثين",       # 30 — most common Iraqi form

    # ── D. Hundreds ───────────────────────────────────────────────────────────
    # 100 — miya variants (note: مير/ميت handled by SAFE_NUMBER_CORRECTIONS)
    "مية":           "مئة",          # 100
    "ميه":           "مئة",          # 100
    "الميه":         "مئة",          # 100 — with definite article
    "المية":         "مئة",          # 100 — with definite article

    # 200
    "ميتين":         "مئتين",        # 200
    "مئتان":         "مئتين",        # 200 — dual nominative → accusative

    # 300
    "ثلاثمية":       "ثلاثمئة",      # 300
    "تلاثمية":       "ثلاثمئة",      # 300
    "ثلاث مية":      "ثلاثمئة",      # 300 — spaced spoken form
    "ثلاث ميه":      "ثلاثمئة",      # 300
    "تلاث مية":      "ثلاثمئة",      # 300
    "تلاث ميه":      "ثلاثمئة",      # 300
    "تلثمية":        "ثلاثمئة",      # 300 — further reduced form
    "تلثميه":        "ثلاثمئة",      # 300

    # 400
    "اربعمية":       "أربعمئة",      # 400
    "أربعمية":       "أربعمئة",      # 400
    "اربعميه":       "أربعمئة",      # 400
    "اربع مية":      "أربعمئة",      # 400
    "اربع ميه":      "أربعمئة",      # 400
    "أربع مية":      "أربعمئة",      # 400
    "أربع ميه":      "أربعمئة",      # 400

    # 500
    "خمسمية":        "خمسمئة",       # 500
    "خمسميه":        "خمسمئة",       # 500
    "خمس مية":       "خمسمئة",       # 500
    "خمس ميه":       "خمسمئة",       # 500

    # 600
    "ستمية":         "ستمئة",        # 600
    "ستميه":         "ستمئة",        # 600
    "ست مية":        "ستمئة",        # 600
    "ست ميه":        "ستمئة",        # 600

    # 700
    "سبعمية":        "سبعمئة",       # 700
    "سبعميه":        "سبعمئة",       # 700
    "سبع مية":       "سبعمئة",       # 700
    "سبع ميه":       "سبعمئة",       # 700

    # 800
    "ثمنمية":        "ثمانمئة",      # 800 — reduced ثمان→ثمن
    "ثمانمية":       "ثمانمئة",      # 800
    "ثمانميه":       "ثمانمئة",      # 800
    "ثمنميه":        "ثمانمئة",      # 800
    "ثمان مية":      "ثمانمئة",      # 800
    "ثمان ميه":      "ثمانمئة",      # 800
    "ثمن مية":       "ثمانمئة",      # 800

    # 900
    "تسعمية":        "تسعمئة",       # 900
    "تسعميه":        "تسعمئة",       # 900
    "تسع مية":       "تسعمئة",       # 900
    "تسع ميه":       "تسعمئة",       # 900
}

# ── 3. NUMBER_VALUES ──────────────────────────────────────────────────────────
# Canonical word/phrase (post-normalization) → integer.
# Keys are the TARGET forms produced by SAFE_NUMBER_CORRECTIONS + NUMBER_VARIANTS.
# Multi-word forms (e.g. "احد عشر") are matched as a unit by the downstream parser.
NUMBER_VALUES: dict[str, int] = {
    # Units
    "واحد":          1,
    "اثنين":         2,
    "ثلاثة":         3,
    "أربعة":         4,
    "خمسة":          5,
    "ستة":           6,
    "سبعة":          7,
    "ثمانية":        8,
    "تسعة":          9,
    "عشرة":         10,
    # Teens
    "احد عشر":      11,
    "اثنا عشر":     12,
    "ثلاثة عشر":    13,
    "أربعة عشر":    14,
    "خمسة عشر":     15,
    "ستة عشر":      16,
    "سبعة عشر":     17,
    "ثمانية عشر":   18,
    "تسعة عشر":     19,
    # Tens
    "عشرين":        20,
    "ثلاثين":       30,
    "اربعين":       40,
    "خمسين":        50,
    "ستين":         60,
    "سبعين":        70,
    "ثمانين":       80,
    "تسعين":        90,
    # Hundreds
    "مئة":         100,
    "مئتين":       200,
    "ثلاثمئة":     300,
    "أربعمئة":     400,
    "خمسمئة":      500,
    "ستمئة":       600,
    "سبعمئة":      700,
    "ثمانمئة":     800,
    "تسعمئة":      900,
}

# ── 4. MULTIPLIERS ────────────────────────────────────────────────────────────
# Scale words → integer multiplier.
# The downstream parser accumulates a sub-total, multiplies by the scale, then
# resets for the next group.  ألفين / مليونين encode both multiplier and value.
MULTIPLIERS: dict[str, int] = {
    "ألف":           1_000,
    "الف":           1_000,        # non-hamza spelling
    "آلاف":          1_000,        # plural
    "الاف":          1_000,        # non-hamza plural
    "ألفين":         2_000,        # dual — fixed value, no preceding coefficient
    "الفين":         2_000,
    "مليون":     1_000_000,
    "مليونين":   2_000_000,        # dual — fixed value
    "ملايين":    1_000_000,        # plural
    "مليار": 1_000_000_000,
    "مليارين":2_000_000_000,       # dual — fixed value
    "مليارات":1_000_000_000,       # plural
}


# ── Demo normalization helper (used by __main__ block only) ───────────────────

def _normalize(text: str) -> str:
    """Apply SAFE_NUMBER_CORRECTIONS then NUMBER_VARIANTS to a text string."""
    import re
    # Pre-step: insert space after conjunction و that is glued to the next word.
    # e.g. "مليون وميه" → "مليون و ميه" so the word-boundary regex can match ميه.
    # Only triggers when و is preceded by a space (i.e. it starts a "word" token).
    text = re.sub(r'(?<= )و(?=\S)', 'و ', text)
    # Pass 1: SAFE corrections (longest key first)
    for k, v in sorted(SAFE_NUMBER_CORRECTIONS.items(), key=lambda x: -len(x[0])):
        text = re.sub(r'(?<!\w)' + re.escape(k) + r'(?!\w)', v, text)
    # Pass 2: dialect variants (longest key first — handles spaced forms first)
    for k, v in sorted(NUMBER_VARIANTS.items(), key=lambda x: -len(x[0])):
        text = re.sub(r'(?<!\w)' + re.escape(k) + r'(?!\w)', v, text)
    return text


def _parse_int(text: str) -> int | None:
    """
    Demo integer parser: normalize then greedily convert canonical Arabic
    number text to an integer using NUMBER_VALUES + MULTIPLIERS.

    Iraqi financial convention:
      • After a million group, an un-multiplied hundred (مئة…تسعمئة) is
        treated as × 1 000 (i.e. مئة = مئة ألف = 100 000).
        e.g.  مليون وميه  →  مليون ومئة  →  1 000 000 + 100 000 = 1 100 000
    """
    import re
    normalized = _normalize(text)
    # Split on whitespace only.  Do NOT split on و (\u0648) because و is a
    # letter in many Arabic words (مليون, عشرون, …).  The _normalize pre-step
    # already inserts a space after conjunction و, so "و" appears as its own
    # token when appropriate.
    tokens = normalized.split()

    total   = 0
    current = 0   # accumulator for the current group
    after_million = False

    i = 0
    while i < len(tokens):
        # Try two-word NUMBER_VALUES match first (احد عشر, اثنا عشر, …)
        if i + 1 < len(tokens):
            two = tokens[i] + " " + tokens[i + 1]
            if two in NUMBER_VALUES:
                current += NUMBER_VALUES[two]
                i += 2
                continue

        tok = tokens[i]

        if tok in NUMBER_VALUES:
            v = NUMBER_VALUES[tok]
            # Iraqi financial convention: مئة-scale after million → ×1000
            if after_million and 100 <= v <= 900:
                v *= 1_000
            current += v
            i += 1
            continue

        if tok in MULTIPLIERS:
            m = MULTIPLIERS[tok]
            if m in (2_000, 2_000_000, 2_000_000_000):
                # Dual forms are fixed values — no preceding coefficient
                total += m
                current = 0
            elif m >= 1_000_000:
                coeff = current if current else 1
                total += coeff * m
                current = 0
                after_million = True
                i += 1
                continue
            else:  # ألف/آلاف
                coeff = current if current else 1
                total += coeff * m
                current = 0
                after_million = False
            i += 1
            continue

        i += 1  # unknown token — skip

    total += current
    return total if total > 0 else None


# ── Tests / demo ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # (A) Normalization tests — verify canonical Arabic text output
    norm_tests: list[tuple[str, str]] = [
        ("مير",            "مئة"),
        ("ميت",            "مئة"),
        ("مية",            "مئة"),
        ("ميه",            "مئة"),
        ("مية وخمسين",     "مئة و خمسين"),   # space inserted after conjunction و
        ("ستمية",          "ستمئة"),
        ("ثمنمية",         "ثمانمئة"),
        ("خمستعش",         "خمسة عشر"),
        ("ثنعش",           "اثنا عشر"),
        ("تلاثين",         "ثلاثين"),
    ]

    print("=" * 60)
    print("§ A — Normalization (text → canonical Arabic)")
    print("=" * 60)
    all_ok = True
    for src, expected in norm_tests:
        got    = _normalize(src)
        status = "✓" if got == expected else f"✗  expected: {expected}"
        if got != expected:
            all_ok = False
        print(f"  {src:<22} →  {got:<22} {status}")

    # (B) Integer parsing tests — canonical text → int
    int_tests: list[tuple[str, int]] = [
        ("خمسين ألف",          50_000),
        ("مية وخمسين ألف",    150_000),
        ("ستمية",                  600),
        ("ثمنمية",                 800),
        ("مليون وميه",       1_100_000),  # Iraqi fin. convention: ميه = مئة ألف
    ]

    print()
    print("=" * 60)
    print("§ B — Integer parsing (canonical text → int)")
    print("=" * 60)
    for src, expected in int_tests:
        got    = _parse_int(src)
        status = "✓" if got == expected else f"✗  expected: {expected:,}"
        if got != expected:
            all_ok = False
        got_str = f"{got:,}" if got is not None else "None"
        print(f"  {src:<26} →  {got_str:<14} {status}")

    print()
    print("All tests passed ✓" if all_ok else "Some tests FAILED ✗")
