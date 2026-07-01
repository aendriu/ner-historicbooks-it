#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <dirent.h>
#include <sys/stat.h>
#include "cJSON.h"

// Dynamic string buffer for our text processing
typedef struct {
    char *str;
    size_t len;
    size_t cap;
} StringBuffer;

void sb_init(StringBuffer *sb, size_t initial_cap) {
    sb->cap = initial_cap > 1024 ? initial_cap : 1024;
    sb->str = malloc(sb->cap);
    sb->len = 0;
    sb->str[0] = '\0';
}

void sb_append(StringBuffer *sb, const char *s, size_t slen) {
    if (sb->len + slen + 1 > sb->cap) {
        sb->cap = (sb->len + slen + 1) * 2;
        sb->str = realloc(sb->str, sb->cap);
    }
    memcpy(sb->str + sb->len, s, slen);
    sb->len += slen;
    sb->str[sb->len] = '\0';
}

void sb_append_char(StringBuffer *sb, char c) {
    if (sb->len + 2 > sb->cap) {
        sb->cap *= 2;
        sb->str = realloc(sb->str, sb->cap);
    }
    sb->str[sb->len++] = c;
    sb->str[sb->len] = '\0';
}

void sb_free(StringBuffer *sb) {
    free(sb->str);
}

int is_vowel(char c) {
    c = tolower(c);
    return (c == 'a' || c == 'e' || c == 'i' || c == 'o' || c == 'u');
}

int is_word_char_str(const char *text, int idx) {
    unsigned char uc = (unsigned char)text[idx];
    if (isalpha(uc) || isdigit(uc)) return 1;
    if (uc == '\'') return 1;
    if (uc == 0xE2 && text[idx+1] == (char)0x80 && text[idx+2] == (char)0x99) return 1;
    if (uc == 0x80 && idx > 0 && (unsigned char)text[idx-1] == 0xE2) return 1;
    if (uc == 0x99 && idx > 1 && (unsigned char)text[idx-2] == 0xE2) return 1;
    // Italian accented characters: C3 followed by 80-BF
    if (uc == 0xC3 && text[idx+1] != '\0') {
        unsigned char next = (unsigned char)text[idx+1];
        if (next >= 0x80 && next <= 0xBF) {
            return 1;
        }
    }
    // Also check if THIS byte is the continuation byte of an accented character
    if (uc >= 0x80 && uc <= 0xBF && idx > 0) {
        unsigned char prev = (unsigned char)text[idx-1];
        if (prev == 0xC3) return 1;
    }
    return 0;
}

int is_invalid_terminal_consonant(char c) {
    unsigned char uc = (unsigned char)c;
    if (!isalpha(uc)) return 0;
    c = toupper(c);
    return (c == 'B' || c == 'C' || c == 'F' || c == 'G' || c == 'J' || 
            c == 'K' || c == 'M' || c == 'P' || c == 'Q' || c == 'S' || 
            c == 'T' || c == 'V' || c == 'W' || c == 'X' || c == 'Y' || c == 'Z');
}

// Function to replace all occurrences of a substring
char *str_replace(const char *orig, const char *rep, const char *with) {
    char *result;
    const char *ins;
    char *tmp;
    int len_rep;
    int len_with;
    int len_front;
    int count;

    if (!orig || !rep) return NULL;
    len_rep = strlen(rep);
    if (len_rep == 0) return NULL;
    if (!with) with = "";
    len_with = strlen(with);

    ins = orig;
    for (count = 0; (tmp = strstr(ins, rep)); ++count) {
        ins = tmp + len_rep;
    }

    if (count == 0) {
        return strdup(orig);
    }

    tmp = result = malloc(strlen(orig) + (len_with - len_rep) * count + 1);
    if (!result) return NULL;

    while (count--) {
        ins = strstr(orig, rep);
        len_front = ins - orig;
        tmp = strncpy(tmp, orig, len_front) + len_front;
        tmp = strcpy(tmp, with) + len_with;
        orig += len_front + len_rep;
    }
    strcpy(tmp, orig);
    return result;
}

const char* special_chars[] = {
    "■", "•", "►", "♦", "_", "^", "|", "<", ">", "\\", "*", "=", "~", "±", "✓", "¬", NULL
};

char* remove_special_chars(const char *text) {
    char *current = strdup(text);
    for (int i = 0; special_chars[i] != NULL; i++) {
        char *old = current;
        current = str_replace(current, special_chars[i], "");
        free(old);
    }
    return current;
}

char* clean_word_endings(const char *text) {
    int len = strlen(text);
    char *res = malloc(len + 1);
    int r = 0;
    
    for (int i = 0; i < len; i++) {
        if (is_word_char_str(text, i)) {
            int j = i;
            while (j < len && is_word_char_str(text, j)) {
                j++;
            }
            int end = j - 1;
            int has_dot = (j < len && text[j] == '.');
            int has_apos = (j < len && (text[j] == '\'' || ((unsigned char)text[j] == 0xE2 && (unsigned char)text[j+1] == 0x80 && (unsigned char)text[j+2] == 0x99)));
            
            if (!has_dot && !has_apos) {
                int word_len = j - i;
                int is_all_caps = 1;
                for (int k = i; k <= end; k++) {
                    if (islower(text[k])) is_all_caps = 0;
                }
                
                while (end >= i && is_invalid_terminal_consonant(text[end])) {
                    int should_strip = 0;
                    if (word_len == 2) {
                        should_strip = 1; // Garbage like 'wm'
                    } else if (word_len == 1 && islower(text[end])) {
                        should_strip = 1; // Garbage like 'm'
                    } else if (isupper(text[end]) && !is_all_caps) {
                        should_strip = 1; // Mixed case anomaly like MattèoT
                    } else {
                        should_strip = 0; // Preserve BROGNOLIG or randellog for NLP
                    }
                    
                    if (should_strip) {
                        end--;
                        word_len--;
                    } else {
                        break;
                    }
                }
            }
            
            for (int k = i; k <= end; k++) {
                res[r++] = text[k];
            }
            i = j - 1; 
        } else {
            res[r++] = text[i];
        }
    }
    res[r] = '\0';
    return res;
}

char* filter_garbage_tokens(const char *text) {
    int len = strlen(text);
    char *res = malloc(len + 1);
    int r = 0;
    
    for (int i = 0; i < len; i++) {
        // Skip whitespace
        if (isspace(text[i])) {
            res[r++] = text[i];
            continue;
        }
        
        // We are at the start of a token
        int start = i;
        int token_len = 0;
        int alpha_len = 0;
        int vowel_len = 0;
        int upper_len = 0;
        int digit_len = 0;
        
        while (i < len && !isspace(text[i])) {
            token_len++;
            if (is_word_char_str(text, i)) {
                alpha_len++;
                char c = text[i];
                if (isdigit(c)) digit_len++;
                if (is_vowel(c)) vowel_len++;
                if ((unsigned char)c == 0xC3) vowel_len++;
                if (isupper(c)) upper_len++;
            }
            i++;
        }
        
        // Evaluate token
        int keep = 0;
        if (token_len <= 2 && alpha_len >= 1) {
            // Safeguard for "l'", "E,", "A.", etc.
            int has_bad_punct = 0;
            for (int k = start; k < i; k++) {
                if (!is_word_char_str(text, k)) {
                    char c = text[k];
                    if (c != '.' && c != ',' && c != ';' && c != ':' && 
                        c != '!' && c != '?' && c != '\'' && c != '"' && (unsigned char)c < 128) {
                        has_bad_punct = 1;
                        break;
                    }
                }
            }
            if (!has_bad_punct) keep = 1;
        } else if (alpha_len > token_len / 2.0) {
            keep = 1;
        }
        
        // --- NEW HEURISTIC: No-Vowel Garbage Filter ---
        // If a token is mostly or entirely lowercase, has >= 3 letters, and 0 vowels, it's gibberish (e.g. wmm, rnmmm).
        int pure_alpha_len = alpha_len - digit_len;
        if (keep && pure_alpha_len >= 3 && vowel_len == 0 && upper_len < pure_alpha_len) {
            // Extract alpha chars to check exceptions
            char alpha_buf[32];
            int a_idx = 0;
            for (int k = start; k < i && a_idx < 31; k++) {
                if (is_word_char_str(text, k)) {
                    alpha_buf[a_idx++] = tolower(text[k]);
                }
            }
            alpha_buf[a_idx] = '\0';
            
            // Allow common Italian abbreviations without vowels
            if (strcmp(alpha_buf, "srl") != 0 && 
                strcmp(alpha_buf, "snc") != 0 && 
                strcmp(alpha_buf, "cfr") != 0 && 
                strcmp(alpha_buf, "sms") != 0) {
                keep = 0; // It's garbage, delete it!
            }
        }
        
        if (keep) {
            for (int k = start; k < i; k++) {
                res[r++] = text[k];
            }
        }
        
        i--; // Adjust because loop increments i
    }
    res[r] = '\0';
    return res;
}

// Generalized rules based on JSON descriptions
char* apply_general_rules(const char *text) {
    StringBuffer sb;
    size_t len = strlen(text);
    sb_init(&sb, len + 1024);
    
    int quote_open = 0;
    
    for (int i = 0; i < len; i++) {
        char c = text[i];
        
        // Apostrophe merge: [cdlmnstv] + space + ['’] -> c'
        if (i+2 < len && (c == 'c' || c == 'd' || c == 'l' || c == 'm' || c == 'n' || c == 's' || c == 't' || c == 'v' ||
                          c == 'C' || c == 'D' || c == 'L' || c == 'M' || c == 'N' || c == 'S' || c == 'T' || c == 'V')) {
            int isolated = (i == 0 || !is_word_char_str(text, i-1));
            if (isolated && text[i+1] == ' ') {
                if (text[i+2] == '\'') {
                    sb_append_char(&sb, c);
                    sb_append_char(&sb, '\'');
                    i += 2;
                    continue;
                }
                // Check for curly apostrophe ’ (E2 80 99)
                if (i+4 < len && (unsigned char)text[i+2] == 0xE2 && (unsigned char)text[i+3] == 0x80 && (unsigned char)text[i+4] == 0x99) {
                    sb_append_char(&sb, c);
                    sb_append(&sb, "’", 3);
                    i += 4;
                    continue;
                }
            }
        }
        
        // Internal punctuation: a.scriver -> ascriver
        if (is_word_char_str(text, i)) {
            if (i+2 < len) {
                char p = text[i+1];
                if ((p == '.' || p == ',' || p == ';' || p == ':' || p == '!') && is_word_char_str(text, i+2)) {
                    sb_append_char(&sb, c);
                    i += 1;
                    continue;
                }
            }
        }
        
        // Rule 1: 1' -> l' before vowel
        if (c == '1' && i+2 < len && text[i+1] == '\'' && is_vowel(text[i+2])) {
            sb_append(&sb, "l'", 2);
            i++; // skip '
            continue;
        }
        
        // Rule 2 restricted: M atteo -> Matteo
        if (c == 'M' && i+3 < len && text[i+1] == ' ' && text[i+2] == 'a' && text[i+3] == 't') {
            int isolated = (i == 0 || (!isalpha(text[i-1]) && text[i-1] != '.'));
            if (isolated) {
                sb_append_char(&sb, c);
                i++; // skip space
                continue;
            }
        }
        
        // Rule 3: chh -> ch
        if (c == 'c' && i+2 < len && text[i+1] == 'h' && text[i+2] == 'h') {
            sb_append(&sb, "ch", 2);
            i += 2;
            continue;
        }
        
        // Rule 4: -\n -> \n (hyphen at end of line)
        if (c == '-' && i+1 < len && text[i+1] == '\n') {
            continue; // skip hyphen
        }
        
        // Rule 6: " -> « »
        if (c == '"') {
            if (!quote_open) {
                sb_append(&sb, "«", 2); 
                quote_open = 1;
            } else {
                sb_append(&sb, "»", 2);
                quote_open = 0;
            }
            continue;
        }
        // Rule: isolated 0 -> O
        if (c == '0') {
            int isolated = (i == 0 || !is_word_char_str(text, i-1)) && (i+1 == len || !is_word_char_str(text, i+1));
            if (isolated) {
                sb_append_char(&sb, 'O');
                continue;
            }
        }
        
        // Rule 7: 0 at end of word -> remove
        if (c == '0' && i > 0 && isalpha(text[i-1])) {
            int eow = (i+1 == len || !isalpha(text[i+1]));
            if (eow) {
                continue; // remove 0
            }
        }
        
        // Rule 8 & 17: 1 in middle of word -> l or I
        if (c == '1' && i > 0 && isalpha(text[i-1]) && i+1 < len && isalpha(text[i+1])) {
            if (isupper(text[i-1]) && isupper(text[i+1])) {
                sb_append_char(&sb, 'I');
            } else {
                sb_append_char(&sb, 'l');
            }
            continue;
        }
        
        // Rule 9: [0-9] [0-9] -> remove space
        if (isdigit(c) && i+2 < len && text[i+1] == ' ' && isdigit(text[i+2])) {
            sb_append_char(&sb, c);
            i++; // skip space
            continue;
        }
        
        // Rule 10: multiple spaces -> single space
        if (c == ' ' && i+1 < len && text[i+1] == ' ') {
            continue; // skip extra space
        }
        
        // Rule 11 & 13: straight apostrophe -> curly
        if (c == '\'') {
            sb_append(&sb, "’", 3);
            continue;
        }
        
        // Rule 14: piu -> più
        if (c == 'p' && i+3 <= len && strncmp(text+i, "piu", 3) == 0) {
            int wbound_before = (i == 0 || !isalpha(text[i-1]));
            int wbound_after = (i+3 == len || !isalpha(text[i+3]));
            if (wbound_before && wbound_after) {
                sb_append(&sb, "più", 4);
                i += 2;
                continue;
            }
        }
        
        // Rule 15: 1 at start before capital: \b1 [A-Z] -> I [A-Z]
        if (c == '1' && (i == 0 || !isalpha(text[i-1])) && i+2 < len && text[i+1] == ' ' && isupper(text[i+2])) {
            sb_append_char(&sb, 'I');
            continue;
        }
        
        // Rule 16: 0 in middle of capitals: [A-Z]0[A-Z]
        if (c == '0' && i > 0 && isupper(text[i-1]) && i+1 < len && isupper(text[i+1])) {
            sb_append_char(&sb, 'O');
            continue;
        }
        
        // Rule 18: 1 at end of capital word: [A-Z]1\b
        if (c == '1' && i > 0 && isupper(text[i-1])) {
            int eow = (i+1 == len || !isalpha(text[i+1]));
            if (eow) {
                sb_append_char(&sb, 'I');
                continue;
            }
        }
        
        // Rule 19: 1 at start of word -> l
        if (c == '1' && (i == 0 || !isalpha(text[i-1])) && i+1 < len && islower(text[i+1])) {
            sb_append_char(&sb, 'l');
            continue;
        }
        
        // Rule 20: et -> e
        if (c == 'e' && i+2 <= len && strncmp(text+i, "et", 2) == 0) {
            int wbound_before = (i == 0 || !is_word_char_str(text, i-1));
            int wbound_after = (i+2 == len || !is_word_char_str(text, i+2));
            if (wbound_before && wbound_after) {
                sb_append(&sb, "e", 1);
                i += 1;
                continue;
            }
        }

        // Rule 21: insi no -> insino
        if (c == 'i' && i+7 <= len && strncmp(text+i, "insi no", 7) == 0) {
            sb_append(&sb, "insino", 6);
            i += 6;
            continue;
        }
        
        if (c == 'C' && i+13 <= len && strncmp(text+i, "Capitoloprimo", 13) == 0) {
            sb_append(&sb, "Capitolo primo", 14);
            i += 12;
            continue;
        }
        if (c == 'E' && i+10 <= len && strncmp(text+i, "Edizionedi", 10) == 0) {
            sb_append(&sb, "Edizione di", 11);
            i += 9;
            continue;
        }

        sb_append_char(&sb, c);
    }
    
    return sb.str;
}

char* apply_semantic_fixes(const char *text) {
    size_t len = strlen(text);
    StringBuffer sb;
    sb_init(&sb, len + 1024);
    
    for (int i = 0; i < len; i++) {
        char c = text[i];
        
        if (i + 1 < len && text[i+1] == ' ' && (isupper((unsigned char)c) || c == '0')) {
            int isolated = (i == 0 || (!isalpha((unsigned char)text[i-1]) && text[i-1] != '\''));
            if (isolated) {
                int is_cons = (c != 'A' && c != 'E' && c != 'I' && c != 'O' && c != 'U');
                int should_merge = is_cons;
                char merge_char = c;
                
                if (c == '0') {
                    merge_char = 'O';
                    is_cons = 0;
                }
                
                if (!is_cons) {
                    if (c == 'A' && strncmp(text + i + 2, "riosto", 6) == 0 && !isalpha((unsigned char)text[i+8])) should_merge = 1;
                    else if ((c == 'O' || c == '0') && strncmp(text + i + 2, "rlando", 6) == 0 && !isalpha((unsigned char)text[i+8])) should_merge = 1;
                    else if ((c == 'O' || c == '0') && strncmp(text + i + 2, "riand", 5) == 0) should_merge = 1;
                    else if (c == 'I' && strncmp(text + i + 2, "nghilterra", 10) == 0 && !isalpha((unsigned char)text[i+12])) should_merge = 1;
                    else if (c == 'O' && strncmp(text + i + 2, "nde", 3) == 0 && !isalpha((unsigned char)text[i+5])) should_merge = 1;
                    else if (c == 'U' && strncmp(text + i + 2, "rbino", 5) == 0 && !isalpha((unsigned char)text[i+7])) should_merge = 1;
                    else if (c == 'I' && strncmp(text + i + 2, "o ", 2) == 0) should_merge = 1;
                    else if (c == 'I' && strncmp(text + i + 2, "Spagna", 6) == 0 && !isalpha((unsigned char)text[i+8])) {
                        sb_append(&sb, "In", 2);
                        i++;
                        continue;
                    }
                }
                
                if (should_merge) {
                    sb_append_char(&sb, merge_char);
                    i++;
                    continue;
                }
            }
        }
        sb_append_char(&sb, c);
    }
    
    char *merged = strdup(sb.str);
    sb_free(&sb);
    
    struct {
        const char *orig;
        const char *rep;
    } dict[] = {
        {"peri tipi", "per i tipi"},
        {"ma gnanimità", "magnanimità"},
        {"incli nazione", "inclinazione"},
        {"col pa", "colpa"},
        {"Beliosi", "Bellosi"},
        {"Fra’ iovanni", "Fra' Giovanni"},
        {"Fra' iovanni", "Fra' Giovanni"},
        {"Antonio EePiero Poliamoli", "Antonio e Piero Pollaiolo"},
        {"G uglielmo da M ardila", "Guglielmo da Marcillat"},
        {"M arco Caiavrese", "Marco Calavrese"},
        {"iulio Ili", "Giulio III"},
        {"PTassitele", "Prassitele"},
        {"Cap. Ili", "Cap. III"},
        {"Cap. IMI", "Cap. VIII"},
        {"Cap. X II II", "Cap. XIV"},
        {"Cap. XVII II", "Cap. XVIII"},
        {"Cap. XXVII1110I", "Cap. XXVII"},
        {"Cap 93", "Cap. XCIII"},
        {"Cap 104", "Cap. CIV"},
        {"Cap 117", "Cap. CXVII"},
        {"ALLO ILLUSTRISSIMO E ECCELLENTISSIMO SIGNORE", "ALLO ILLUSTRISSIMO E ECCELLENTISSIMO SIGNORE"},
        {"O riandò", "Orlando"}, 
        {"Oriandò", "Orlando"},
        {NULL, NULL}
    };
    
    char *current = merged;
    for (int j = 0; dict[j].orig != NULL; j++) {
        char *old = current;
        current = str_replace(current, dict[j].orig, dict[j].rep);
        free(old);
    }
    
    return current;
}

void process_json_file(const char *input_path, const char *output_path) {
    FILE *f = fopen(input_path, "rb");
    if (!f) {
        printf("Cannot open %s\n", input_path);
        return;
    }

    fseek(f, 0, SEEK_END);
    long length = ftell(f);
    fseek(f, 0, SEEK_SET);

    char *data = malloc(length + 1);
    fread(data, 1, length, f);
    fclose(f);
    data[length] = '\0';

    cJSON *json = cJSON_Parse(data);
    if (!json) {
        printf("Error parsing JSON in %s: %s\n", input_path, cJSON_GetErrorPtr());
        free(data);
        return;
    }

    cJSON *contenuto = cJSON_GetObjectItemCaseSensitive(json, "contenuto");
    if (cJSON_IsString(contenuto) && (contenuto->valuestring != NULL)) {
        
        // 1. Remove special characters
        char *no_special = remove_special_chars(contenuto->valuestring);
        
        // 2. Apply general OCR rules (like M atteo -> Matteo)
        char *general_cleaned = apply_general_rules(no_special);
        
        // 3. Apply semantic fixes (reconnect dropcaps and specific words)
        char *semantic = apply_semantic_fixes(general_cleaned);
        
        // 4. Remove invalid word endings (B, C, F, G, J, K, M, P, Q, S, T, V, W, X, Y, Z)
        char *no_endings = clean_word_endings(semantic);
        
        // 5. Alpha-Ratio Filter: remove tokens with <= 50% valid letters
        char *cleaned = filter_garbage_tokens(no_endings);
        
        cJSON_ReplaceItemInObject(json, "contenuto", cJSON_CreateString(cleaned));
        
        free(cleaned);
        free(no_endings);
        free(semantic);
        free(general_cleaned);
        free(no_special);
    }

    char *output_data = cJSON_Print(json);
    FILE *out = fopen(output_path, "wb");
    if (out) {
        fputs(output_data, out);
        fclose(out);
    } else {
        printf("Cannot write %s\n", output_path);
    }

    cJSON_Delete(json);
    free(output_data);
    free(data);
}

int main(int argc, char *argv[]) {
    if (argc != 3) {
        printf("Usage: %s <input_dir> <output_dir>\n", argv[0]);
        return 1;
    }

    const char *in_dir = argv[1];
    const char *out_dir = argv[2];

    DIR *d = opendir(in_dir);
    if (!d) {
        printf("Cannot open directory %s\n", in_dir);
        return 1;
    }

    struct dirent *dir;
    while ((dir = readdir(d)) != NULL) {
        if (strstr(dir->d_name, ".json")) {
            char in_path[1024];
            char out_path[1024];
            char base_name[1024];
            
            // Extract base name without .json
            strncpy(base_name, dir->d_name, sizeof(base_name) - 1);
            base_name[sizeof(base_name) - 1] = '\0';
            char *ext = strstr(base_name, ".json");
            if (ext) *ext = '\0';
            
            snprintf(in_path, sizeof(in_path), "%s/%s", in_dir, dir->d_name);
            snprintf(out_path, sizeof(out_path), "%s/%s-cleaned.json", out_dir, base_name);
            printf("Processing %s...\n", dir->d_name);
            process_json_file(in_path, out_path);
        }
    }
    closedir(d);
    printf("Done!\n");

    return 0;
}
