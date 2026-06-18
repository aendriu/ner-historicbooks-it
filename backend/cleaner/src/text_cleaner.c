#define _GNU_SOURCE

#include "text_cleaner.h"

#include <ctype.h>
#include <locale.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include <wctype.h>

// --- Constants ported from preprocessing_py/text_cleaning/constants.py ---

static const wchar_t *STOPWORDS[] = {
    L"il", L"lo", L"la", L"i", L"gli", L"le", L"un", L"uno", L"una",
    L"di", L"a", L"da", L"in", L"con", L"su", L"per", L"tra", L"fra",
    L"che", L"non", L"e", L"o", L"ma", L"se",
    L"ai", L"agli", L"alla", L"alle", L"dello", L"della", L"degli", L"delle",
    L"nello", L"nella", L"negli", L"nelle", L"sullo", L"sulla", L"sugli", L"sulle",
    L"cui", L"chi", L"ne", L"ci", L"vi", L"si", L"mi", L"ti",
};

static const size_t STOPWORDS_COUNT = sizeof(STOPWORDS) / sizeof(STOPWORDS[0]);

static const wchar_t *WHITELIST_H[] = {
    L"ho", L"ha", L"hai", L"hanno", L"ah", L"oh", L"eh", L"ehm", L"uh", L"ih", L"mah",
    L"ahi", L"ohimè", L"ahimè", L"hovvi", L"hammi", L"havvi", L"holle", L"hotti", L"deh",
};
static const size_t WHITELIST_H_COUNT = sizeof(WHITELIST_H) / sizeof(WHITELIST_H[0]);

static const wchar_t *ALLOWED_STARTING_APOSTROPHE[] = {L"'l", L"’l", L"'n", L"’n", L"'d", L"’d"};
static const size_t ALLOWED_STARTING_APOSTROPHE_COUNT =
    sizeof(ALLOWED_STARTING_APOSTROPHE) / sizeof(ALLOWED_STARTING_APOSTROPHE[0]);

static const wchar_t *NOISE_PATTERNS[] = {
    L"H'", L"II", L"LL", L"11", L"F'", L"L'", L"I'", L"H’", L"L’", L"I’", L"F’",
    L"W", L"H", L"F", L"L", L"I", L"1", L"T",
};
static const size_t NOISE_PATTERNS_COUNT = sizeof(NOISE_PATTERNS) / sizeof(NOISE_PATTERNS[0]);

static const wchar_t *ELISION_PREFIXES_A[] = {L"de", L"da", L"ne", L"co", L"su"};
static const size_t ELISION_PREFIXES_A_COUNT = sizeof(ELISION_PREFIXES_A) / sizeof(ELISION_PREFIXES_A[0]);

static const wchar_t *ELISION_PREFIXES_B[] = {
    L"del", L"dal", L"nel", L"col", L"sul", L"al", L"bel", L"quel", L"all", L"dall", L"nell", L"sull", L"coll",
};
static const size_t ELISION_PREFIXES_B_COUNT = sizeof(ELISION_PREFIXES_B) / sizeof(ELISION_PREFIXES_B[0]);

static const wchar_t *HEADER_KEYWORDS[] = {
    L"NOVELLA", L"CAPITOLO", L"LIBRO", L"PARTE", L"TOMO", L"DISCORSI", L"SACRI", L"CANTI", L"POESIE",
};
static const size_t HEADER_KEYWORDS_COUNT = sizeof(HEADER_KEYWORDS) / sizeof(HEADER_KEYWORDS[0]);

// FORBIDDEN_CHARS = set(['*', '>', '<', '|', '+', '^', '=', '£', '$', '%', '€'])
static bool is_forbidden_char(wchar_t c) {
    switch (c) {
        case L'*':
        case L'>':
        case L'<':
        case L'|':
        case L'+':
        case L'^':
        case L'=':
        case L'£':
        case L'$':
        case L'%':
        case L'€':
            return true;
        default:
            return false;
    }
}

static bool is_roman_numeral_token(const wchar_t *t) {
    if (!t || !*t) return false;
    for (const wchar_t *p = t; *p; p++) {
        switch (*p) {
            case L'I':
            case L'V':
            case L'X':
            case L'L':
            case L'C':
            case L'D':
            case L'M':
                break;
            default:
                return false;
        }
    }
    return true;
}

static bool is_vowel(wchar_t c) {
    switch (c) {
        case L'a':
        case L'e':
        case L'i':
        case L'o':
        case L'u':
        case L'A':
        case L'E':
        case L'I':
        case L'O':
        case L'U':
        case L'à':
        case L'è':
        case L'é':
        case L'ì':
        case L'ò':
        case L'ù':
        case L'À':
        case L'È':
        case L'É':
        case L'Ì':
        case L'Ò':
        case L'Ù':
        case L'ó':
        case L'Ó':
        case L'á':
        case L'Á':
        case L'í':
        case L'Í':
        case L'ú':
        case L'Ú':
            return true;
        default:
            return false;
    }
}

static bool wstr_in_list_ci(const wchar_t *s, const wchar_t **list, size_t n) {
    if (!s) return false;
    for (size_t i = 0; i < n; i++) {
        if (wcscasecmp(s, list[i]) == 0) return true;
    }
    return false;
}

static bool wstr_in_list_cs(const wchar_t *s, const wchar_t **list, size_t n) {
    if (!s) return false;
    for (size_t i = 0; i < n; i++) {
        if (wcscmp(s, list[i]) == 0) return true;
    }
    return false;
}

static bool has_any_lowercase_letter(const wchar_t *s) {
    for (const wchar_t *p = s; p && *p; p++) {
        if (iswlower(*p)) return true;
        // handle accented lowercase that locale might not classify: check a limited set
        if (*p == L'à' || *p == L'è' || *p == L'é' || *p == L'ì' || *p == L'ò' || *p == L'ù' ||
            *p == L'ó' || *p == L'á' || *p == L'í' || *p == L'ú')
            return true;
    }
    return false;
}

static bool has_any_letter(const wchar_t *s) {
    for (const wchar_t *p = s; p && *p; p++) {
        if (iswalpha(*p)) return true;
        if (*p == L'à' || *p == L'è' || *p == L'é' || *p == L'ì' || *p == L'ò' || *p == L'ù' ||
            *p == L'À' || *p == L'È' || *p == L'É' || *p == L'Ì' || *p == L'Ò' || *p == L'Ù' ||
            *p == L'ó' || *p == L'Ó' || *p == L'á' || *p == L'Á' || *p == L'í' || *p == L'Í' ||
            *p == L'ú' || *p == L'Ú')
            return true;
    }
    return false;
}

static bool has_any_digit(const wchar_t *s) {
    for (const wchar_t *p = s; p && *p; p++) {
        if (iswdigit(*p)) return true;
    }
    return false;
}

static bool has_any_vowel(const wchar_t *s) {
    for (const wchar_t *p = s; p && *p; p++) {
        if (is_vowel(*p)) return true;
    }
    return false;
}

static bool is_dash_token(const wchar_t *t) {
    return t && (wcscmp(t, L"-") == 0 || wcscmp(t, L"—") == 0 || wcscmp(t, L"–") == 0);
}

static wchar_t *wcsdup_safe(const wchar_t *s) {
    if (!s) return NULL;
    size_t n = wcslen(s);
    wchar_t *out = (wchar_t *)calloc(n + 1, sizeof(wchar_t));
    if (!out) return NULL;
    wcscpy(out, s);
    return out;
}

static wchar_t *wcsndup_safe(const wchar_t *s, size_t n) {
    wchar_t *out = (wchar_t *)calloc(n + 1, sizeof(wchar_t));
    if (!out) return NULL;
    wmemcpy(out, s, n);
    out[n] = 0;
    return out;
}

static bool is_allowed_preprocess_char(wchar_t c) {
    if (iswalpha(c) || iswdigit(c) || iswspace(c)) return true;

    switch (c) {
        case L'.':
        case L',':
        case L';':
        case L':':
        case L'_':
        case L'«':
        case L'»':
        case L'\'':
        case L'’':
        case L'!':
        case L'?':
        case L'$':
        case L'€':
        case L'£':
        case L'%':
        case L'&':
        case L'=':
        case L'+':
        case L'*':
        case L'/':
        case L'(':
        case L')':
        case L'[':
        case L']':
        case L'#':
        case L'-':
        case L'—':
        case L'–':
            return true;
        default:
            return false;
    }
}

static wchar_t *preprocess_text(const wchar_t *input) {
    size_t n = wcslen(input);
    wchar_t *out = (wchar_t *)calloc(n + 1, sizeof(wchar_t));
    if (!out) return NULL;

    size_t j = 0;
    for (size_t i = 0; i < n; i++) {
        if (is_allowed_preprocess_char(input[i])) {
            out[j++] = input[i];
        }
    }
    out[j] = 0;
    return out;
}

static wchar_t *lstrip_punct(const wchar_t *s) {
    // punctuation set used in Python: ".,;:!?()[]{}«»-—–'’"
    const wchar_t *p = s;
    while (*p) {
        wchar_t c = *p;
        if (c == L'.' || c == L',' || c == L';' || c == L':' || c == L'!' || c == L'?' || c == L'(' || c == L')' ||
            c == L'[' || c == L']' || c == L'{' || c == L'}' || c == L'«' || c == L'»' || c == L'-' || c == L'—' ||
            c == L'–' || c == L'\'' || c == L'’') {
            p++;
            continue;
        }
        break;
    }
    return (wchar_t *)p;
}

static void rstrip_punct_inplace(wchar_t *s, const wchar_t *punct) {
    if (!s) return;
    size_t n = wcslen(s);
    while (n > 0) {
        wchar_t c = s[n - 1];
        if (wcschr(punct, c)) {
            s[n - 1] = 0;
            n--;
            continue;
        }
        break;
    }
}

static wchar_t *strip_punct_dup(const wchar_t *s, const wchar_t *punct) {
    const wchar_t *start = s;
    while (*start && wcschr(punct, *start)) start++;
    const wchar_t *end = s + wcslen(s);
    while (end > start && wcschr(punct, end[-1])) end--;
    return wcsndup_safe(start, (size_t)(end - start));
}

static bool is_roman_numeral_after_strip(const wchar_t *t) {
    wchar_t *stripped = strip_punct_dup(t, L".,;:!?()[]{}«»-—–''\"");
    if (!stripped) return false;
    if (stripped[0] == 0) { free(stripped); return false; }
    bool result = is_roman_numeral_token(stripped);
    free(stripped);
    return result;
}

static bool ends_with(const wchar_t *s, const wchar_t *suffix) {
    size_t sl = wcslen(s);
    size_t su = wcslen(suffix);
    if (su > sl) return false;
    return wmemcmp(s + sl - su, suffix, su) == 0;
}

static bool starts_with(const wchar_t *s, const wchar_t *prefix) {
    size_t pl = wcslen(prefix);
    return wmemcmp(s, prefix, pl) == 0;
}

static wchar_t *replace_all_char(const wchar_t *s, wchar_t from, wchar_t to) {
    wchar_t *out = wcsdup_safe(s);
    if (!out) return NULL;
    for (wchar_t *p = out; *p; p++) {
        if (*p == from) *p = to;
    }
    return out;
}

static wchar_t *try_fix_apostrophe_1(const wchar_t *t) {
    if (wcscmp(t, L"1'") == 0 || wcscmp(t, L"1’") == 0) {
        return wcsdup_safe(L"l'");
    }
    if (starts_with(t, L"1'") || starts_with(t, L"1’")) {
        size_t rest_len = wcslen(t + 2);
        wchar_t *out = (wchar_t *)calloc(2 + rest_len + 1, sizeof(wchar_t));
        if (!out) return NULL;
        wcscpy(out, L"l'");
        wcscat(out, t + 2);
        return out;
    }
    return NULL;
}

static wchar_t *try_fix_apostrophe_c(const wchar_t *t) {
    // if t.lower().endswith("'c") or t.lower().endswith("’c"), len<=6 => t[:-1] + "è"
    size_t n = wcslen(t);
    if (n == 0) return NULL;
    if (n <= 6) {
        wchar_t last2[3] = {0};
        if (n >= 2) {
            last2[0] = towlower(t[n - 2]);
            last2[1] = towlower(t[n - 1]);
            last2[2] = 0;
            if ((last2[0] == L'\'' || last2[0] == L'’') && last2[1] == L'c') {
                wchar_t *out = wcsdup_safe(t);
                if (!out) return NULL;
                out[n - 1] = L'è';
                return out;
            }
        }
    }
    return NULL;
}

static wchar_t *fix_starting_I_apostrophe(const wchar_t *t) {
    if (starts_with(t, L"I'") || starts_with(t, L"I’")) {
        size_t n = wcslen(t);
        wchar_t *out = (wchar_t *)calloc(n + 1, sizeof(wchar_t));
        if (!out) return NULL;
        out[0] = L'l';
        wcscpy(out + 1, t + 1);
        return out;
    }
    return NULL;
}

static bool is_ascii_lower_a_z(wchar_t c) { return (c >= L'a' && c <= L'z'); }
static bool is_ascii_upper_a_z(wchar_t c) { return (c >= L'A' && c <= L'Z'); }

static bool is_suffix_letters(const wchar_t *s) {
    for (const wchar_t *p = s; *p; p++) {
        if (iswalpha(*p)) continue;
        // allow explicit accented vowels
        if (*p == L'à' || *p == L'è' || *p == L'é' || *p == L'ì' || *p == L'ò' || *p == L'ù' ||
            *p == L'À' || *p == L'È' || *p == L'É' || *p == L'Ì' || *p == L'Ò' || *p == L'Ù')
            continue;
        return false;
    }
    return true;
}

static wchar_t *fix_internal_noise(const wchar_t *token) {
    // clean_token = token.rstrip(".,;:!?") ; preserve trailing punct
    const wchar_t *punct = L".,;:!?";

    wchar_t *clean = wcsdup_safe(token);
    if (!clean) return NULL;
    size_t orig_len = wcslen(clean);
    rstrip_punct_inplace(clean, punct);

    size_t clean_len = wcslen(clean);
    const wchar_t *trailing = token + clean_len;

    // Find split: prefix(lowercase a-z)+noise(pattern)+suffix(letters)
    // brute-force over noise patterns
    for (size_t pi = 0; pi < NOISE_PATTERNS_COUNT; pi++) {
        const wchar_t *noise = NOISE_PATTERNS[pi];
        size_t noise_len = wcslen(noise);
        if (noise_len == 0 || clean_len <= noise_len) continue;

        // noise must appear after at least 1 ascii lowercase and before at least 1 suffix char
        for (size_t pos = 1; pos + noise_len < clean_len; pos++) {
            // prefix must be all [a-z]+
            bool ok_prefix = true;
            for (size_t k = 0; k < pos; k++) {
                if (!is_ascii_lower_a_z(clean[k])) {
                    ok_prefix = false;
                    break;
                }
            }
            if (!ok_prefix) continue;

            if (wmemcmp(clean + pos, noise, noise_len) != 0) continue;

            const wchar_t *suffix = clean + pos + noise_len;
            if (!*suffix) continue;
            if (!is_suffix_letters(suffix)) continue;

            wchar_t *prefix = wcsndup_safe(clean, pos);
            if (!prefix) {
                free(clean);
                return NULL;
            }

            wchar_t first = suffix[0];
            wchar_t first_lower = towlower(first);
            bool suffix_starts_vowel = is_vowel(first_lower) || is_vowel(first);

            // rule 1: Elisions (dell')
            if (suffix_starts_vowel && wstr_in_list_cs(prefix, ELISION_PREFIXES_A, ELISION_PREFIXES_A_COUNT)) {
                if (wcscmp(noise, L"W") == 0 || wcscmp(noise, L"H") == 0 || wcscmp(noise, L"H'") == 0 ||
                    wcscmp(noise, L"II") == 0 || wcscmp(noise, L"LL") == 0 ||
                    wcscmp(noise, L"11") == 0 || wcscmp(noise, L"H’") == 0) {
                    size_t out_len = wcslen(prefix) + 3 + 1 + wcslen(suffix) + wcslen(trailing) + 1;
                    wchar_t *out = (wchar_t *)calloc(out_len, sizeof(wchar_t));
                    if (!out) {
                        free(prefix);
                        free(clean);
                        return NULL;
                    }
                    wcscpy(out, prefix);
                    wcscat(out, L"ll'");
                    wcscat(out, suffix);
                    wcscat(out, trailing);
                    free(prefix);
                    free(clean);
                    return out;
                }
            }

            if (suffix_starts_vowel && wstr_in_list_cs(prefix, ELISION_PREFIXES_B, ELISION_PREFIXES_B_COUNT)) {
                if (wcscmp(noise, L"F") == 0 || wcscmp(noise, L"H") == 0 || wcscmp(noise, L"L") == 0 ||
                    wcscmp(noise, L"I") == 0 || wcscmp(noise, L"L'") == 0 || wcscmp(noise, L"I'") == 0 ||
                    wcscmp(noise, L"F'") == 0 || wcscmp(noise, L"1") == 0 || wcscmp(noise, L"L’") == 0 ||
                    wcscmp(noise, L"I’") == 0 || wcscmp(noise, L"F’") == 0) {
                    size_t out_len = wcslen(prefix) + 2 + 1 + wcslen(suffix) + wcslen(trailing) + 1;
                    wchar_t *out = (wchar_t *)calloc(out_len, sizeof(wchar_t));
                    if (!out) {
                        free(prefix);
                        free(clean);
                        return NULL;
                    }
                    wcscpy(out, prefix);
                    wcscat(out, L"l'");
                    wcscat(out, suffix);
                    wcscat(out, trailing);
                    free(prefix);
                    free(clean);
                    return out;
                }
            }

            // rule 2: consonants (afTanno -> affanno)
            size_t prefix_len = wcslen(prefix);
            if (prefix_len > 0 && prefix[prefix_len - 1] == L'f' && wcscmp(noise, L"T") == 0) {
                size_t out_len = prefix_len + 1 + wcslen(suffix) + wcslen(trailing) + 1;
                wchar_t *out = (wchar_t *)calloc(out_len, sizeof(wchar_t));
                if (!out) {
                    free(prefix);
                    free(clean);
                    return NULL;
                }
                wcscpy(out, prefix);
                wcscat(out, L"f");
                wcscat(out, suffix);
                wcscat(out, trailing);
                free(prefix);
                free(clean);
                return out;
            }

            free(prefix);
        }
    }

    (void)orig_len;
    free(clean);
    return NULL;
}

static wchar_t *fix_internal_uppercase(const wchar_t *token) {
    // Port of TokenCorrector.fix_internal_uppercase
    const wchar_t *strip_punct = L".,;:!?";
    wchar_t *clean = wcsdup_safe(token);
    if (!clean) return NULL;
    rstrip_punct_inplace(clean, strip_punct);
    size_t clean_len = wcslen(clean);
    const wchar_t *trailing = token + clean_len;

    // match ^([a-zàèéìòù\'’]+)([A-Z])([a-zàèéìòù]+)$
    // We'll scan for a single uppercase ASCII letter where:
    //  - left side is lower/accents/apostrophe
    //  - right side is lower/accents
    for (size_t i = 1; i + 1 < clean_len; i++) {
        if (!is_ascii_upper_a_z(clean[i])) continue;

        bool ok_prefix = true;
        for (size_t k = 0; k < i; k++) {
            wchar_t c = clean[k];
            if (c == L'\'' || c == L'’') continue;
            if (is_ascii_lower_a_z(c)) continue;
            // allow lowercase accented vowels
            if (c == L'à' || c == L'è' || c == L'é' || c == L'ì' || c == L'ò' || c == L'ù') continue;
            ok_prefix = false;
            break;
        }
        if (!ok_prefix) continue;

        bool ok_suffix = true;
        for (size_t k = i + 1; k < clean_len; k++) {
            wchar_t c = clean[k];
            if (is_ascii_lower_a_z(c)) continue;
            if (c == L'à' || c == L'è' || c == L'é' || c == L'ì' || c == L'ò' || c == L'ù') continue;
            ok_suffix = false;
            break;
        }
        if (!ok_suffix) continue;

        wchar_t *prefix = wcsndup_safe(clean, i);
        wchar_t upper = clean[i];
        wchar_t *suffix = wcsdup_safe(clean + i + 1);
        if (!prefix || !suffix) {
            free(prefix);
            free(suffix);
            free(clean);
            return NULL;
        }

        // elision fixes
        if (upper == L'L' || upper == L'I') {
            // elision_prefixes = ELISION_PREFIXES_B + ['gl','dell','dall','nell','sull','coll']
            static const wchar_t *extra[] = {L"gl", L"dell", L"dall", L"nell", L"sull", L"coll"};
            bool is_elision_prefix = wstr_in_list_cs(prefix, ELISION_PREFIXES_B, ELISION_PREFIXES_B_COUNT);
            if (!is_elision_prefix) {
                for (size_t ei = 0; ei < sizeof(extra) / sizeof(extra[0]); ei++) {
                    if (wcscmp(prefix, extra[ei]) == 0) {
                        is_elision_prefix = true;
                        break;
                    }
                }
            }

            if (is_elision_prefix && suffix[0] && is_vowel(suffix[0])) {
                bool prefix_ends_ll = ends_with(prefix, L"ll");
                size_t out_len = wcslen(prefix) + 2 + wcslen(suffix) + wcslen(trailing) + 1;
                wchar_t *out = (wchar_t *)calloc(out_len, sizeof(wchar_t));
                if (!out) {
                    free(prefix);
                    free(suffix);
                    free(clean);
                    return NULL;
                }
                wcscpy(out, prefix);
                if (prefix_ends_ll) {
                    wcscat(out, L"'");
                } else {
                    wcscat(out, L"l'");
                }
                wcscat(out, suffix);
                wcscat(out, trailing);
                free(prefix);
                free(suffix);
                free(clean);
                return out;
            }
        }

        if (upper == L'A' || upper == L'E' || upper == L'I' || upper == L'O' || upper == L'U') {
            if (ends_with(prefix, L"ll") || ends_with(prefix, L"un") || ends_with(prefix, L"on") || ends_with(prefix, L"an")) {
                size_t out_len = wcslen(prefix) + 1 + 1 + wcslen(suffix) + wcslen(trailing) + 1;
                wchar_t *out = (wchar_t *)calloc(out_len, sizeof(wchar_t));
                if (!out) {
                    free(prefix);
                    free(suffix);
                    free(clean);
                    return NULL;
                }
                wcscpy(out, prefix);
                wcscat(out, L"'");
                wchar_t mid[2] = {upper, 0};
                wcscat(out, mid);
                wcscat(out, suffix);
                wcscat(out, trailing);
                free(prefix);
                free(suffix);
                free(clean);
                return out;
            }
        }

        if (upper == L'I') {
            size_t out_len = wcslen(prefix) + 1 + wcslen(suffix) + wcslen(trailing) + 1;
            wchar_t *out = (wchar_t *)calloc(out_len, sizeof(wchar_t));
            if (!out) {
                free(prefix);
                free(suffix);
                free(clean);
                return NULL;
            }
            wcscpy(out, prefix);
            wcscat(out, L"l");
            wcscat(out, suffix);
            wcscat(out, trailing);
            free(prefix);
            free(suffix);
            free(clean);
            return out;
        }

        free(prefix);
        free(suffix);
    }

    // special case: d'AIessandria
    // match2 ^([a-zàèéìòù\'’]+)([A-Z])([A-Z])([a-zàèéìòù]+)$ and u1==A u2==I and prefix endswith apostrophe
    for (size_t i = 1; i + 2 < clean_len; i++) {
        if (!(is_ascii_upper_a_z(clean[i]) && is_ascii_upper_a_z(clean[i + 1]))) continue;

        bool ok_prefix = true;
        for (size_t k = 0; k < i; k++) {
            wchar_t c = clean[k];
            if (c == L'\'' || c == L'’') continue;
            if (is_ascii_lower_a_z(c)) continue;
            if (c == L'à' || c == L'è' || c == L'é' || c == L'ì' || c == L'ò' || c == L'ù') continue;
            ok_prefix = false;
            break;
        }
        if (!ok_prefix) continue;

        bool ok_suffix = true;
        for (size_t k = i + 2; k < clean_len; k++) {
            wchar_t c = clean[k];
            if (is_ascii_lower_a_z(c)) continue;
            if (c == L'à' || c == L'è' || c == L'é' || c == L'ì' || c == L'ò' || c == L'ù') continue;
            ok_suffix = false;
            break;
        }
        if (!ok_suffix) continue;

        wchar_t u1 = clean[i];
        wchar_t u2 = clean[i + 1];
        if (u1 != L'A' || u2 != L'I') continue;

        wchar_t *prefix = wcsndup_safe(clean, i);
        if (!prefix) {
            free(clean);
            return NULL;
        }
        size_t prefix_len = wcslen(prefix);
        if (prefix_len == 0 || !(prefix[prefix_len - 1] == L'\'' || prefix[prefix_len - 1] == L'’')) {
            free(prefix);
            continue;
        }

        wchar_t *suffix = wcsdup_safe(clean + i + 2);
        if (!suffix) {
            free(prefix);
            free(clean);
            return NULL;
        }

        size_t out_len = wcslen(prefix) + 1 + 1 + wcslen(suffix) + wcslen(trailing) + 1;
        wchar_t *out = (wchar_t *)calloc(out_len, sizeof(wchar_t));
        if (!out) {
            free(prefix);
            free(suffix);
            free(clean);
            return NULL;
        }
        wcscpy(out, prefix);
        wcscat(out, L"A");
        wcscat(out, L"l");
        wcscat(out, suffix);
        wcscat(out, trailing);

        free(prefix);
        free(suffix);
        free(clean);
        return out;
    }

    free(clean);
    return NULL;
}

static wchar_t *fix_mixed_1(const wchar_t *t) {
    bool has_1 = false;
    bool has_alpha = false;
    bool has_other_digit = false;

    for (const wchar_t *p = t; *p; p++) {
        if (*p == L'1') has_1 = true;
        if (iswalpha(*p) || *p == L'à' || *p == L'è' || *p == L'é' || *p == L'ì' || *p == L'ò' || *p == L'ù' ||
            *p == L'À' || *p == L'È' || *p == L'É' || *p == L'Ì' || *p == L'Ò' || *p == L'Ù')
            has_alpha = true;
        if (iswdigit(*p) && *p != L'1') has_other_digit = true;
    }

    if (!(has_1 && has_alpha && !has_other_digit)) return NULL;

    size_t n = wcslen(t);
    wchar_t *out = wcsdup_safe(t);
    if (!out) return NULL;

    if (n >= 2 && (ends_with(out, L"'1") || ends_with(out, L"’1"))) {
        out[n - 1] = L'l';
        return out;
    }

    if (out[0] == L'1') {
        // if len>1 and t[1]=='l' -> 'I' + rest with 1->l
        if (n > 1 && out[1] == L'l') {
            out[0] = L'I';
            for (size_t i = 1; i < n; i++) {
                if (out[i] == L'1') out[i] = L'l';
            }
            return out;
        }
        out[0] = L'l';
        for (size_t i = 1; i < n; i++) {
            if (out[i] == L'1') out[i] = L'l';
        }
        return out;
    }

    for (size_t i = 0; i < n; i++) {
        if (out[i] == L'1') out[i] = L'l';
    }
    return out;
}

static bool is_valid_token(const wchar_t *t);

static wchar_t *replace_confusable_digits(const wchar_t *t, bool one_to_i) {
    size_t n = wcslen(t);
    wchar_t *out = wcsdup_safe(t);
    if (!out) return NULL;

    bool lower_ctx = has_any_lowercase_letter(t);

    for (size_t i = 0; i < n; i++) {
        if (out[i] == L'1') {
            if (one_to_i) {
                out[i] = lower_ctx ? L'i' : L'I';
            } else {
                out[i] = lower_ctx ? L'l' : L'L';
            }
        } else if (out[i] == L'0') {
            out[i] = lower_ctx ? L'o' : L'O';
        } else if (out[i] == L'5') {
            out[i] = lower_ctx ? L's' : L'S';
        }
    }

    return out;
}

static wchar_t *fix_common_ocr_digits(const wchar_t *t) {
    bool has_alpha = false;
    bool has_digit = false;

    for (const wchar_t *p = t; *p; p++) {
        if (iswdigit(*p)) {
            has_digit = true;
            if (!(*p == L'0' || *p == L'1' || *p == L'5')) return NULL;
        }
        if (iswalpha(*p) || *p == L'à' || *p == L'è' || *p == L'é' || *p == L'ì' || *p == L'ò' || *p == L'ù' ||
            *p == L'À' || *p == L'È' || *p == L'É' || *p == L'Ì' || *p == L'Ò' || *p == L'Ù') {
            has_alpha = true;
        }
    }

    if (!(has_alpha && has_digit)) return NULL;

    wchar_t *cand_i = replace_confusable_digits(t, true);
    if (cand_i) {
        if (is_valid_token(cand_i)) return cand_i;
        free(cand_i);
    }

    wchar_t *cand_l = replace_confusable_digits(t, false);
    if (cand_l) {
        if (is_valid_token(cand_l)) return cand_l;
        free(cand_l);
    }

    return NULL;
}

static size_t count_char(const wchar_t *s, wchar_t c) {
    size_t count = 0;
    for (const wchar_t *p = s; p && *p; p++) {
        if (*p == c) count++;
    }
    return count;
}

static bool is_alpha_only_after_strip(const wchar_t *s) {
    // check_content.isalpha() after stripping spaces and apostrophes and punct
    for (const wchar_t *p = s; *p; p++) {
        if (*p == L' ') continue;
        if (*p == L'\'' || *p == L'’') continue;
        if (*p == L'.' || *p == L',' || *p == L';' || *p == L':' || *p == L'!' || *p == L'?' || *p == L'(' || *p == L')' ||
            *p == L'[' || *p == L']' || *p == L'{' || *p == L'}' || *p == L'«' || *p == L'»')
            continue;
        if (!iswalpha(*p) && *p != L'à' && *p != L'è' && *p != L'é' && *p != L'ì' && *p != L'ò' && *p != L'ù' &&
            *p != L'À' && *p != L'È' && *p != L'É' && *p != L'Ì' && *p != L'Ò' && *p != L'Ù' &&
            *p != L'ó' && *p != L'Ó' && *p != L'á' && *p != L'Á' && *p != L'í' && *p != L'Í' &&
            *p != L'ú' && *p != L'Ú')
            return false;
    }
    return true;
}

static wchar_t *fix_internal_dots(const wchar_t *t) {
    if (!wcschr(t, L'.')) return NULL;
    if (count_char(t, L'.') == 1 && ends_with(t, L".")) return NULL;

    wchar_t *temp = replace_all_char(t, L'.', L' ');
    if (!temp) return NULL;

    if (ends_with(t, L".")) {
        // ensure final '.'
        size_t n = wcslen(temp);
        if (n > 0) temp[n - 1] = L'.';
    }

    if (is_alpha_only_after_strip(temp)) {
        return temp;
    }

    free(temp);
    return NULL;
}

static wchar_t *fix_roman_numeral_ocr(const wchar_t *t) {
    // Fix OCR errors in Roman numerals: J→I, 1→I
    const wchar_t *punct = L".,;:!?";
    wchar_t *clean = wcsdup_safe(t);
    if (!clean) return NULL;
    size_t orig_len = wcslen(clean);
    rstrip_punct_inplace(clean, punct);
    size_t clean_len = wcslen(clean);
    const wchar_t *trailing = t + clean_len;

    if (clean_len == 0 || clean_len > 20) { free(clean); return NULL; }

    // Must be all Roman-numeral-like chars (I,V,X,L,C,D,M) plus confusables (J,j,1)
    bool has_confusable = false;
    for (size_t i = 0; i < clean_len; i++) {
        wchar_t c = clean[i];
        if (c == L'I' || c == L'V' || c == L'X' || c == L'L' ||
            c == L'C' || c == L'D' || c == L'M') continue;
        if (c == L'J' || c == L'j' || c == L'1') { has_confusable = true; continue; }
        free(clean);
        return NULL;
    }

    if (!has_confusable) { free(clean); return NULL; }

    // Replace J/j→I, 1→I
    wchar_t *fixed = wcsdup_safe(clean);
    if (!fixed) { free(clean); return NULL; }
    for (size_t i = 0; i < clean_len; i++) {
        if (fixed[i] == L'J' || fixed[i] == L'j') fixed[i] = L'I';
        if (fixed[i] == L'1') fixed[i] = L'I';
    }

    if (!is_roman_numeral_token(fixed)) {
        free(fixed); free(clean); return NULL;
    }

    // Reconstruct with trailing punct
    size_t out_len = wcslen(fixed) + wcslen(trailing) + 1;
    wchar_t *out = (wchar_t *)calloc(out_len, sizeof(wchar_t));
    if (!out) { free(fixed); free(clean); return NULL; }
    wcscpy(out, fixed);
    wcscat(out, trailing);

    (void)orig_len;
    free(fixed);
    free(clean);
    return out;
}

static wchar_t *try_fix_token(const wchar_t *t) {
    wchar_t *res = NULL;

    res = try_fix_apostrophe_1(t);
    if (res) return res;

    res = try_fix_apostrophe_c(t);
    if (res) return res;

    res = fix_starting_I_apostrophe(t);
    if (res) return res;

    res = fix_internal_noise(t);
    if (res) return res;

    res = fix_internal_uppercase(t);
    if (res) return res;

    res = fix_common_ocr_digits(t);
    if (res) return res;

    res = fix_mixed_1(t);
    if (res) return res;

    res = fix_roman_numeral_ocr(t);
    if (res) return res;

    res = fix_internal_dots(t);
    if (res) return res;

    return NULL;
}

static wchar_t *fix_11_contextual(const wchar_t *token, const wchar_t *next_token) {
    if (wcscmp(token, L"11") != 0 || !next_token) return NULL;

    const wchar_t *clean_next = lstrip_punct(next_token);
    if (clean_next && *clean_next && iswlower(*clean_next)) {
        return wcsdup_safe(L"Il");
    }
    // also consider accented lowercase not recognized by locale
    if (clean_next && *clean_next) {
        wchar_t c = *clean_next;
        if (c == L'à' || c == L'è' || c == L'é' || c == L'ì' || c == L'ò' || c == L'ù' || c == L'ó' || c == L'á' || c == L'í' || c == L'ú') {
            return wcsdup_safe(L"Il");
        }
    }
    return NULL;
}

static bool token_contains_header_keyword(const wchar_t *t) {
    for (size_t i = 0; i < HEADER_KEYWORDS_COUNT; i++) {
        if (wcsstr(t, HEADER_KEYWORDS[i]) != NULL) return true;
    }
    return false;
}

static bool token_is_headerish(const wchar_t *t) {
    if (!t || !*t) return false;
    wchar_t c = t[0];
    if (is_ascii_upper_a_z(c) || iswdigit(c)) return true;
    if (is_roman_numeral_token(t)) return true;
    return false;
}

static wchar_t *resolve_attached_header(const wchar_t *token, const wchar_t **next_tokens, size_t next_count, size_t *consumed) {
    *consumed = 0;

    // match: ^([a-zàèéìòù\'’]+)([-—–]?)([A-Z0-9].*)$
    size_t n = wcslen(token);
    size_t i = 0;

    // prefix: lower/accents/apostrophe
    while (i < n) {
        wchar_t c = token[i];
        if (c == L'\'' || c == L'’') {
            i++;
            continue;
        }
        if (is_ascii_lower_a_z(c) || c == L'à' || c == L'è' || c == L'é' || c == L'ì' || c == L'ò' || c == L'ù') {
            i++;
            continue;
        }
        break;
    }

    if (i == 0 || i >= n) return NULL;

    // optional sep
    if (token[i] == L'-' || token[i] == L'—' || token[i] == L'–') {
        i++;
        if (i >= n) return NULL;
    }

    wchar_t start = token[i];
    if (!(is_ascii_upper_a_z(start) || iswdigit(start))) return NULL;

    wchar_t *prefix = wcsndup_safe(token, i == 0 ? 0 : (token[i - 1] == L'-' || token[i - 1] == L'—' || token[i - 1] == L'–') ? (i - 1) : i);
    if (!prefix) return NULL;

    const wchar_t *header_start = token + i;

    bool is_dirty_header = has_any_lowercase_letter(header_start);
    if (is_dirty_header) {
        if (next_count == 0) {
            free(prefix);
            return NULL;
        }
        const wchar_t *first_next = next_tokens[0];
        if (!token_is_headerish(first_next)) {
            free(prefix);
            return NULL;
        }
    }

    size_t local_consumed = 0;
    const wchar_t *suffix = NULL;

    for (size_t ti = 0; ti < next_count; ti++) {
        const wchar_t *t = next_tokens[ti];
        wchar_t *clean_t = strip_punct_dup(t, L".,;:!?()[]{}«»-—–'’");
        if (!clean_t) {
            free(prefix);
            return NULL;
        }
        if (clean_t[0] == 0) {
            local_consumed++;
            free(clean_t);
            continue;
        }
        free(clean_t);

        if (has_any_lowercase_letter(t)) {
            const wchar_t *clean_start = lstrip_punct(t);
            if (clean_start && *clean_start && (iswlower(*clean_start) ||
                                                *clean_start == L'à' || *clean_start == L'è' || *clean_start == L'é' ||
                                                *clean_start == L'ì' || *clean_start == L'ò' || *clean_start == L'ù')) {
                suffix = t;
                local_consumed++;
                size_t out_len = wcslen(prefix) + 1;
                wchar_t *out = (wchar_t *)calloc(out_len, sizeof(wchar_t));
                if (!out) {
                    free(prefix);
                    return NULL;
                }
                wcscpy(out, prefix);
                // Evita concatenazioni spurie (es. "vogliamodartene"):
                // qui rimuoviamo solo l'interruzione header e lasciamo il token successivo intatto.
                (void)suffix;
                *consumed = local_consumed - 1;
                free(prefix);
                return out;
            }
            break;
        }

        local_consumed++;
    }

    // Fallback: rimuovi header dal token corrente, preservando punteggiatura finale di header_start
    wchar_t trailing_punct[16] = {0};
    size_t tp = 0;
    size_t hs_len = wcslen(header_start);
    while (hs_len > 0) {
        wchar_t c = header_start[hs_len - 1];
        if (c == L'.' || c == L',' || c == L';' || c == L':' || c == L'!' || c == L'?') {
            if (tp < 15) trailing_punct[tp++] = c;
            hs_len--;
            continue;
        }
        break;
    }
    // reverse trailing_punct
    for (size_t a = 0; a < tp / 2; a++) {
        wchar_t tmp = trailing_punct[a];
        trailing_punct[a] = trailing_punct[tp - 1 - a];
        trailing_punct[tp - 1 - a] = tmp;
    }
    trailing_punct[tp] = 0;

    size_t out_len = wcslen(prefix) + wcslen(trailing_punct) + 1;
    wchar_t *out = (wchar_t *)calloc(out_len, sizeof(wchar_t));
    if (!out) {
        free(prefix);
        return NULL;
    }
    wcscpy(out, prefix);
    wcscat(out, trailing_punct);

    free(prefix);
    *consumed = 0;
    return out;
}

static wchar_t *resolve_detached_header(const wchar_t *token, const wchar_t **next_tokens, size_t next_count, size_t *consumed) {
    *consumed = 0;

    // token must be ^[a-zàèéìòù\'’]+$
    for (const wchar_t *p = token; *p; p++) {
        wchar_t c = *p;
        if (c == L'\'' || c == L'’') continue;
        if (is_ascii_lower_a_z(c) || c == L'à' || c == L'è' || c == L'é' || c == L'ì' || c == L'ò' || c == L'ù') continue;
        return NULL;
    }

    if (next_count == 0) return NULL;
    if (!token_is_headerish(next_tokens[0])) return NULL;

    size_t local_consumed = 0;
    bool has_keyword = false;
    const wchar_t *suffix = NULL;

    // collect header tokens
    for (size_t i = 0; i < next_count; i++) {
        const wchar_t *t = next_tokens[i];

        if (has_any_lowercase_letter(t)) {
            const wchar_t *clean_start = lstrip_punct(t);
            if (clean_start && *clean_start && (iswlower(*clean_start) ||
                                                *clean_start == L'à' || *clean_start == L'è' || *clean_start == L'é' ||
                                                *clean_start == L'ì' || *clean_start == L'ò' || *clean_start == L'ù')) {
                suffix = t;
                break;
            }
            break;
        }

        // header token
        local_consumed++;

        if (token_contains_header_keyword(t)) has_keyword = true;
    }

    if (local_consumed == 0) return NULL;

    // Require a keyword (CAPITOLO, NOVELLA, etc.) to treat this as a header interruption.
    // Bare Roman numerals/numbers after lowercase words (e.g. "secolo XIX") are normal text.
    if (!has_keyword) return NULL;

    // If stopword, keep separated
    if (wstr_in_list_ci(token, STOPWORDS, STOPWORDS_COUNT)) {
        *consumed = local_consumed;
        return wcsdup_safe(token);
    }

    if (suffix) {
        size_t out_len = wcslen(token) + 1;
        wchar_t *out = (wchar_t *)calloc(out_len, sizeof(wchar_t));
        if (!out) return NULL;
        wcscpy(out, token);
        // Evita concatenazioni spurie (es. "voceconobbe,").
        // Manteniamo separato il token successivo e consumiamo solo i token header.
        (void)suffix;
        *consumed = local_consumed;
        return out;
    }

    *consumed = local_consumed;
    return wcsdup_safe(token);
}

static wchar_t *resolve_generic_header_interruption(const wchar_t *token, const wchar_t **next_tokens, size_t next_count, size_t *consumed) {
    wchar_t *res = resolve_attached_header(token, next_tokens, next_count, consumed);
    if (res) return res;
    res = resolve_detached_header(token, next_tokens, next_count, consumed);
    if (res) return res;
    *consumed = 0;
    return NULL;
}

static bool is_valid_token(const wchar_t *t);
static bool is_valid_token_with_reason(const wchar_t *t, const char **reason);

static bool g_debug_invalid_inited = false;
static bool g_debug_invalid_enabled = false;
static size_t g_debug_invalid_printed = 0;
static const size_t G_DEBUG_INVALID_MAX = 200;

static bool debug_invalid_enabled(void) {
    if (!g_debug_invalid_inited) {
        const char *v = getenv("PREPROCESS_DEBUG_INVALID");
        if (v && (*v == '1' || *v == 'y' || *v == 'Y' || *v == 't' || *v == 'T')) {
            g_debug_invalid_enabled = true;
        }
        g_debug_invalid_inited = true;
    }
    return g_debug_invalid_enabled;
}

static void debug_print_invalid(const wchar_t *token, const char *reason) {
    if (!debug_invalid_enabled()) return;
    if (g_debug_invalid_printed >= G_DEBUG_INVALID_MAX) return;

    char buf[768];
    size_t n = wcstombs(buf, token, sizeof(buf) - 1);
    if (n == (size_t)-1) {
        strcpy(buf, "<token-non-convertibile>");
    } else {
        buf[n] = 0;
    }

    fprintf(stderr, "SCARTATO[%s]: %s\n", reason ? reason : "unknown", buf);
    g_debug_invalid_printed++;
}

static void append_token(wchar_t ***arr, size_t *count, size_t *cap, wchar_t *tok_owned) {
    if (*count + 1 > *cap) {
        size_t new_cap = (*cap == 0) ? 256 : (*cap * 2);
        wchar_t **new_arr = (wchar_t **)realloc(*arr, new_cap * sizeof(wchar_t *));
        if (!new_arr) {
            free(tok_owned);
            return;
        }
        *arr = new_arr;
        *cap = new_cap;
    }
    (*arr)[(*count)++] = tok_owned;
}

static void validate_and_collect(const wchar_t *candidate, wchar_t ***out, size_t *count, size_t *cap) {
    if (!candidate) return;
    const wchar_t *space = wcschr(candidate, L' ');
    if (space) {
        wchar_t *tmp = wcsdup_safe(candidate);
        if (!tmp) return;
        wchar_t *saveptr = NULL;
        wchar_t *tok = wcstok(tmp, L" \t\n\r\f\v", &saveptr);
        while (tok) {
            const char *reason = NULL;
            if (is_valid_token_with_reason(tok, &reason)) {
                append_token(out, count, cap, wcsdup_safe(tok));
            } else {
                debug_print_invalid(tok, reason);
            }
            tok = wcstok(NULL, L" \t\n\r\f\v", &saveptr);
        }
        free(tmp);
        return;
    }

    const char *reason = NULL;
    if (is_valid_token_with_reason(candidate, &reason)) {
        append_token(out, count, cap, wcsdup_safe(candidate));
    } else {
        debug_print_invalid(candidate, reason);
    }
}

static bool check_basic_structure(const wchar_t *t) {
    bool has_vowel = has_any_vowel(t);
    bool has_number = has_any_digit(t);
    bool is_roman = is_roman_numeral_token(t) || is_roman_numeral_after_strip(t);

    // elision exception: no vowel and endswith apostrophe but has letters
    size_t n = wcslen(t);
    if (!has_vowel && n > 0 && (t[n - 1] == L'\'' || t[n - 1] == L'’')) {
        if (has_any_letter(t)) return true;
    }

    if (is_dash_token(t)) return true;

    if (wstr_in_list_cs(t, ALLOWED_STARTING_APOSTROPHE, ALLOWED_STARTING_APOSTROPHE_COUNT)) return true;

    return has_vowel || has_number || is_roman;
}

static bool check_single_char(const wchar_t *t) {
    size_t n = wcslen(t);
    if (n > 1) return true;
    if (is_dash_token(t)) return true;

    wchar_t c = towlower(t[0]);
    const wchar_t *allowed = L"aeioàèéìòù0123456789";
    if (wcschr(allowed, c)) return true;
    if (iswupper(t[0])) return true;
    return false;
}

static bool check_forbidden_chars(const wchar_t *t) {
    for (const wchar_t *p = t; *p; p++) {
        if (is_forbidden_char(*p)) return false;
    }
    return true;
}

static bool is_alnum_extended(wchar_t c) {
    if (iswalpha(c) || iswdigit(c)) return true;
    switch (c) {
        case L'à':
        case L'è':
        case L'é':
        case L'ì':
        case L'ò':
        case L'ù':
        case L'À':
        case L'È':
        case L'É':
        case L'Ì':
        case L'Ò':
        case L'Ù':
            return true;
        default:
            return false;
    }
}

static bool check_symbol_density(const wchar_t *t) {
    // remove « »
    size_t n = wcslen(t);
    if (n == 0) return false;

    size_t len_clean = 0;
    size_t alnum_count = 0;

    for (const wchar_t *p = t; *p; p++) {
        if (*p == L'«' || *p == L'»') continue;
        len_clean++;
        if (is_alnum_extended(*p)) alnum_count++;
    }

    if (len_clean == 0) return false;
    if (len_clean > 1) {
        double ratio = (double)alnum_count / (double)len_clean;
        if (ratio < 0.5) return false;
    }
    return true;
}

static bool is_all_upper(const wchar_t *t) {
    bool seen_alpha = false;
    for (const wchar_t *p = t; *p; p++) {
        if (iswalpha(*p)) {
            seen_alpha = true;
            if (!iswupper(*p)) return false;
        }
    }
    return seen_alpha;
}

static bool is_all_lower(const wchar_t *t) {
    bool seen_alpha = false;
    for (const wchar_t *p = t; *p; p++) {
        if (iswalpha(*p)) {
            seen_alpha = true;
            if (!iswlower(*p)) {
                // allow accented lowercase not classified
                if (!(*p == L'à' || *p == L'è' || *p == L'é' || *p == L'ì' || *p == L'ò' || *p == L'ù' ||
                      *p == L'ó' || *p == L'á' || *p == L'í' || *p == L'ú'))
                    return false;
            }
        }
    }
    return seen_alpha;
}

static bool is_titlecase_like(const wchar_t *t) {
    // Find first letter; it must be uppercase, and all subsequent letters must be lowercase.
    bool first_letter_found = false;
    for (const wchar_t *p = t; *p; p++) {
        if (!iswalpha(*p) && !(*p == L'à' || *p == L'è' || *p == L'é' || *p == L'ì' || *p == L'ò' || *p == L'ù' ||
                               *p == L'À' || *p == L'È' || *p == L'É' || *p == L'Ì' || *p == L'Ò' || *p == L'Ù'))
            continue;
        if (!first_letter_found) {
            first_letter_found = true;
            if (!iswupper(*p)) return false;
        } else {
            if (!iswlower(*p)) {
                if (!(*p == L'à' || *p == L'è' || *p == L'é' || *p == L'ì' || *p == L'ò' || *p == L'ù' ||
                      *p == L'ó' || *p == L'á' || *p == L'í' || *p == L'ú'))
                    return false;
            }
        }
    }
    return first_letter_found;
}

static bool check_casing(const wchar_t *t) {
    if (is_all_upper(t) || is_all_lower(t) || is_titlecase_like(t)) return true;

    // Reject internal uppercase not at 0, unless preceded by apostrophe or dash.
    for (size_t i = 0; t[i]; i++) {
        if (iswupper(t[i])) {
            if (i == 0) continue;
            wchar_t prev = t[i - 1];
            if (prev == L'\'' || prev == L'’') continue;
            if (prev == L'-' || prev == L'—' || prev == L'–') continue;
            return false;
        }
    }
    return true;
}

static bool check_foreign_ending(const wchar_t *t) {
    size_t n = wcslen(t);
    if (n == 0) return false;
    wchar_t c = t[n - 1];
    c = towlower(c);
    return !(c == L'k' || c == L'w' || c == L'x' || c == L'y' || c == L'j');
}

static __attribute__((unused)) bool contains_substr_ci(const wchar_t *hay, const wchar_t *needle) {
    if (!hay || !needle || !*needle) return false;
    size_t hn = wcslen(hay);
    size_t nn = wcslen(needle);
    for (size_t i = 0; i + nn <= hn; i++) {
        bool ok = true;
        for (size_t j = 0; j < nn; j++) {
            if (towlower(hay[i + j]) != towlower(needle[j])) {
                ok = false;
                break;
            }
        }
        if (ok) return true;
    }
    return false;
}

static wchar_t *wstr_to_lower_dup(const wchar_t *s) {
    size_t n = wcslen(s);
    wchar_t *out = (wchar_t *)calloc(n + 1, sizeof(wchar_t));
    if (!out) return NULL;
    for (size_t i = 0; i < n; i++) out[i] = towlower(s[i]);
    out[n] = 0;
    return out;
}

static bool check_h_usage(const wchar_t *t) {
    const wchar_t *clean_start = lstrip_punct(t);
    if (clean_start && *clean_start && iswupper(*clean_start)) return true;

    wchar_t *lower = wstr_to_lower_dup(t);
    if (!lower) return true;

    if (wcschr(lower, L'h')) {
        // remove ch, gh, ph
        // naive scan-build removing those pairs
        size_t n = wcslen(lower);
        wchar_t *tmp = (wchar_t *)calloc(n + 1, sizeof(wchar_t));
        if (!tmp) {
            free(lower);
            return true;
        }
        size_t j = 0;
        for (size_t i = 0; i < n; i++) {
            if (i + 1 < n) {
                if ((lower[i] == L'c' && lower[i + 1] == L'h') || (lower[i] == L'g' && lower[i + 1] == L'h') ||
                    (lower[i] == L'p' && lower[i + 1] == L'h')) {
                    tmp[j++] = lower[i];
                    i++; // skip 'h'
                    continue;
                }
            }
            tmp[j++] = lower[i];
        }
        tmp[j] = 0;

        if (wcschr(tmp, L'h')) {
            // If the original token (stripped) is all lowercase letters
            // (with optional accented vowels/apostrophes), it's likely a
            // valid archaic Italian or Latin word — allow it.
            {
                const wchar_t *p = lstrip_punct(t);
                bool all_lower_alpha = (p && *p);
                for (const wchar_t *c = p; c && *c; c++) {
                    wchar_t ch = *c;
                    if (ch >= L'a' && ch <= L'z') continue;
                    if (ch == L'\'' || ch == L'\u2019') continue;
                    if (ch == L'à' || ch == L'è' || ch == L'é' || ch == L'ì' || ch == L'ò' || ch == L'ù') continue;
                    // allow trailing punctuation
                    if (ch == L'.' || ch == L',' || ch == L';' || ch == L':' || ch == L'!' || ch == L'?') {
                        // only if all remaining chars are also punctuation
                        bool rest_punct = true;
                        for (const wchar_t *r = c + 1; *r; r++) {
                            if (!(*r == L'.' || *r == L',' || *r == L';' || *r == L':' || *r == L'!' || *r == L'?')) {
                                rest_punct = false;
                                break;
                            }
                        }
                        if (rest_punct) break;
                    }
                    all_lower_alpha = false;
                    break;
                }
                if (all_lower_alpha) {
                    free(tmp);
                    free(lower);
                    return true;
                }
            }

            // clean_t = strip punctuation then strip apostrophes
            wchar_t *clean = strip_punct_dup(lower, L".,;:!?()[]{}«»-—–");
            if (!clean) {
                free(tmp);
                free(lower);
                return true;
            }
            // strip apostrophes around
            wchar_t *clean2 = strip_punct_dup(clean, L"'’");
            free(clean);
            if (!clean2) {
                free(tmp);
                free(lower);
                return true;
            }

            bool ok = wstr_in_list_ci(clean2, WHITELIST_H, WHITELIST_H_COUNT);
            if (!ok) {
                for (size_t wi = 0; wi < WHITELIST_H_COUNT; wi++) {
                    size_t wl = wcslen(WHITELIST_H[wi]);
                    size_t cl = wcslen(clean2);
                    if (cl > wl + 1) {
                        // endswith "'" + w or "’" + w
                        if (clean2[cl - wl - 1] == L'\'' || clean2[cl - wl - 1] == L'’') {
                            if (wcscasecmp(clean2 + cl - wl, WHITELIST_H[wi]) == 0) {
                                ok = true;
                                break;
                            }
                        }
                    }
                }
            }

            free(clean2);
            free(tmp);
            free(lower);
            return ok;
        }

        free(tmp);
    }

    free(lower);
    return true;
}

static bool check_double_vowels(const wchar_t *t) {
    wchar_t *lower = wstr_to_lower_dup(t);
    if (!lower) return true;
    bool ok = !(wcsstr(lower, L"aa") || wcsstr(lower, L"uu"));
    free(lower);
    return ok;
}

static bool check_starting_apostrophe(const wchar_t *t) {
    if (wstr_in_list_cs(t, ALLOWED_STARTING_APOSTROPHE, ALLOWED_STARTING_APOSTROPHE_COUNT)) return true;
    if (t[0] == L'\'' || t[0] == L'’') {
        return wcslen(t) > 2;
    }
    return true;
}

static bool check_mixed_alphanumeric(const wchar_t *t) {
    bool has_alpha = false;
    bool has_digit = false;
    for (const wchar_t *p = t; *p; p++) {
        if (iswdigit(*p)) has_digit = true;
        if (iswalpha(*p) || is_alnum_extended(*p)) {
            if (!iswdigit(*p)) has_alpha = true;
        }
    }
    if (has_alpha && has_digit) return false;
    return true;
}

static bool is_valid_token_with_reason(const wchar_t *t, const char **reason) {
    if (!check_basic_structure(t)) {
        if (reason) *reason = "basic_structure";
        return false;
    }
    if (!check_single_char(t)) {
        if (reason) *reason = "single_char";
        return false;
    }
    if (!check_forbidden_chars(t)) {
        if (reason) *reason = "forbidden_chars";
        return false;
    }

    // Roman numerals bypass remaining checks (casing, foreign_ending, h_usage, etc.)
    if (is_roman_numeral_after_strip(t)) {
        if (reason) *reason = NULL;
        return true;
    }

    if (!check_symbol_density(t)) {
        if (reason) *reason = "symbol_density";
        return false;
    }
    if (!check_casing(t)) {
        if (reason) *reason = "casing";
        return false;
    }
    if (!check_foreign_ending(t)) {
        if (reason) *reason = "foreign_ending";
        return false;
    }
    if (!check_h_usage(t)) {
        if (reason) *reason = "h_usage";
        return false;
    }
    if (!check_double_vowels(t)) {
        if (reason) *reason = "double_vowels";
        return false;
    }
    if (!check_starting_apostrophe(t)) {
        if (reason) *reason = "starting_apostrophe";
        return false;
    }
    if (!check_mixed_alphanumeric(t)) {
        if (reason) *reason = "mixed_alnum";
        return false;
    }

    if (reason) *reason = NULL;
    return true;
}

static bool is_valid_token(const wchar_t *t) { return is_valid_token_with_reason(t, NULL); }

static size_t calculate_weighted_length(const wchar_t *t) {
    wchar_t *clean = strip_punct_dup(t, L".,;:!?()[]{}«»-—–'’");
    if (!clean) return 0;
    if (clean[0] == 0) {
        free(clean);
        return 0;
    }

    size_t len_t = wcslen(t);
    bool upper = is_all_upper(clean) && wcslen(clean) > 1;
    bool roman = is_roman_numeral_token(clean);
    free(clean);

    if (upper || roman) {
        return len_t > 5 ? len_t : 5;
    }
    return len_t;
}

static void remove_garbage_sequences(wchar_t ***tokens, size_t *count) {
    const size_t window_size = 15;
    const double avg_len_threshold = 2.5;
    if (*count < window_size) return;

    size_t n = *count;
    size_t *wlen = (size_t *)calloc(n, sizeof(size_t));
    if (!wlen) return;
    for (size_t i = 0; i < n; i++) wlen[i] = calculate_weighted_length((*tokens)[i]);

    bool *bad = (bool *)calloc(n, sizeof(bool));
    if (!bad) {
        free(wlen);
        return;
    }

    for (size_t i = 0; i + window_size <= n; i++) {
        size_t sum = 0;
        size_t short_tokens = 0;
        size_t low_alpha_tokens = 0;

        for (size_t j = 0; j < window_size; j++) sum += wlen[i + j];

        for (size_t j = 0; j < window_size; j++) {
            const wchar_t *tok = (*tokens)[i + j];
            wchar_t *core = strip_punct_dup(tok, L".,;:!?()[]{}«»-—–'’");
            size_t core_len = core ? wcslen(core) : 0;

            if (core_len > 0 && core_len <= 2) short_tokens++;

            if (core_len > 0) {
                size_t alpha = 0;
                for (size_t k = 0; core[k]; k++) {
                    if (iswalpha(core[k])) alpha++;
                }
                if (alpha == 0 || ((double)alpha / (double)core_len) < 0.6) {
                    low_alpha_tokens++;
                }
            }

            free(core);
        }

        double avg = (double)sum / (double)window_size;

        // Più conservativo: elimina solo finestre chiaramente rumorose
        if (avg < avg_len_threshold && short_tokens >= 12 && low_alpha_tokens >= 6) {
            for (size_t j = 0; j < window_size; j++) bad[i + j] = true;
        }
    }

    // compact
    size_t out_i = 0;
    for (size_t i = 0; i < n; i++) {
        if (!bad[i]) {
            (*tokens)[out_i++] = (*tokens)[i];
        } else {
            free((*tokens)[i]);
        }
    }
    *count = out_i;

    free(bad);
    free(wlen);
}

static wchar_t *process_tokens(wchar_t **tokens, size_t token_count) {
    wchar_t **out = NULL;
    size_t out_count = 0;
    size_t out_cap = 0;

    for (size_t i = 0; i < token_count; i++) {
        wchar_t *t = tokens[i];
        const wchar_t *next_t = (i + 1 < token_count) ? tokens[i + 1] : NULL;

        // Phase 1: contextual merges/corrections
        wchar_t *fixed11 = fix_11_contextual(t, next_t);
        if (fixed11) {
            free(t);
            t = fixed11;
            tokens[i] = t;
        }

        const wchar_t *next_window[9] = {0};
        size_t next_count = 0;
        for (size_t k = 0; k < 9 && (i + 1 + k) < token_count; k++) {
            next_window[k] = tokens[i + 1 + k];
            next_count++;
        }

        size_t consumed = 0;
        wchar_t *merged = resolve_generic_header_interruption(t, next_window, next_count, &consumed);
        if (merged) {
            free(t);
            t = merged;
            tokens[i] = t;
            // mark consumed tokens as empty (will be skipped)
            for (size_t c = 0; c < consumed; c++) {
                size_t idx = i + 1 + c;
                if (idx < token_count) {
                    // Preserve Roman numeral tokens consumed by header resolution
                    wchar_t *consumed_tok = tokens[idx];
                    if (consumed_tok && *consumed_tok) {
                        wchar_t *stripped = strip_punct_dup(consumed_tok, L".,;:!?()[]{}«»-—–''\"");
                        bool keep = stripped && stripped[0] && is_roman_numeral_token(stripped);
                        free(stripped);
                        if (keep) continue;  // leave this token in place for normal processing
                    }
                    free(tokens[idx]);
                    tokens[idx] = wcsdup_safe(L"");
                }
            }
        }

        // Phase 2: single token correction
        wchar_t *corrected = try_fix_token(t);
        const wchar_t *candidate = corrected ? corrected : t;

        // Phase 3: validate and collect
        validate_and_collect(candidate, &out, &out_count, &out_cap);

        if (corrected) free(corrected);
    }

    remove_garbage_sequences(&out, &out_count);

    // Join with spaces
    size_t total = 0;
    for (size_t i = 0; i < out_count; i++) total += wcslen(out[i]) + 1;
    wchar_t *joined = (wchar_t *)calloc(total + 1, sizeof(wchar_t));
    if (!joined) {
        for (size_t i = 0; i < out_count; i++) free(out[i]);
        free(out);
        return NULL;
    }

    wchar_t *p = joined;
    for (size_t i = 0; i < out_count; i++) {
        size_t len = wcslen(out[i]);
        wmemcpy(p, out[i], len);
        p += len;
        if (i + 1 < out_count) *p++ = L' ';
        free(out[i]);
    }
    *p = 0;

    free(out);
    return joined;
}

static wchar_t **split_tokens(const wchar_t *text, size_t *out_count) {
    *out_count = 0;
    if (!text || !*text) return NULL;

    wchar_t *tmp = wcsdup_safe(text);
    if (!tmp) return NULL;

    size_t cap = 1024;
    wchar_t **tokens = (wchar_t **)calloc(cap, sizeof(wchar_t *));
    if (!tokens) {
        free(tmp);
        return NULL;
    }

    wchar_t *saveptr = NULL;
    wchar_t *tok = wcstok(tmp, L" \t\n\r\f\v", &saveptr);
    while (tok) {
        if (*out_count >= cap) {
            cap *= 2;
            wchar_t **new_tokens = (wchar_t **)realloc(tokens, cap * sizeof(wchar_t *));
            if (!new_tokens) break;
            tokens = new_tokens;
        }
        tokens[(*out_count)++] = wcsdup_safe(tok);
        tok = wcstok(NULL, L" \t\n\r\f\v", &saveptr);
    }

    free(tmp);
    return tokens;
}

static void free_tokens(wchar_t **tokens, size_t count) {
    if (!tokens) return;
    for (size_t i = 0; i < count; i++) free(tokens[i]);
    free(tokens);
}

char *clean_text_utf8(const char *input_utf8) {
    if (!input_utf8) return strdup("");

    // Ensure locale for wide conversions
    static bool locale_set = false;
    if (!locale_set) {
        // Lambda environments can start with non-UTF-8 locale; force UTF-8 when possible.
        const char *loc = setlocale(LC_ALL, "");
        if (!loc || !strstr(loc, "UTF-8")) {
            loc = setlocale(LC_ALL, "C.UTF-8");
        }
        if (!loc || !strstr(loc, "UTF-8")) {
            loc = setlocale(LC_ALL, "en_US.UTF-8");
        }
        locale_set = true;
    }

    // Convert to wide
    size_t in_len = strlen(input_utf8);
    size_t wcap = in_len + 1;
    wchar_t *wbuf = (wchar_t *)calloc(wcap, sizeof(wchar_t));
    if (!wbuf) return NULL;

    mbstate_t st;
    memset(&st, 0, sizeof(st));
    const char *src = input_utf8;
    size_t converted = mbsrtowcs(wbuf, &src, wcap - 1, &st);
    if (converted == (size_t)-1) {
        // Retry once after forcing UTF-8 locale, then fallback to raw bytes.
        setlocale(LC_ALL, "C.UTF-8");
        memset(&st, 0, sizeof(st));
        src = input_utf8;
        converted = mbsrtowcs(wbuf, &src, wcap - 1, &st);
    }
    if (converted == (size_t)-1) {
        free(wbuf);
        return strdup(input_utf8);
    }
    wbuf[converted] = 0;

    wchar_t *pre = preprocess_text(wbuf);
    free(wbuf);
    if (!pre) return NULL;

    size_t tok_count = 0;
    wchar_t **tokens = split_tokens(pre, &tok_count);
    free(pre);
    if (!tokens && tok_count == 0) {
        return strdup("");
    }

    wchar_t *cleaned_w = process_tokens(tokens, tok_count);
    free_tokens(tokens, tok_count);
    if (!cleaned_w) return strdup("");

    // Convert back to UTF-8
    size_t out_cap = wcslen(cleaned_w) * 6 + 1;
    char *out = (char *)calloc(out_cap, 1);
    if (!out) {
        free(cleaned_w);
        return NULL;
    }

    mbstate_t st2;
    memset(&st2, 0, sizeof(st2));
    const wchar_t *wsrc = cleaned_w;
    size_t out_len = wcsrtombs(out, &wsrc, out_cap - 1, &st2);
    if (out_len == (size_t)-1) {
        free(cleaned_w);
        free(out);
        return strdup("");
    }
    out[out_len] = 0;

    free(cleaned_w);
    return out;
}
