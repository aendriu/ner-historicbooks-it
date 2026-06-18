#define _GNU_SOURCE

#include "text_cleaner.h"

#if __has_include("cJSON.h")
#include "cJSON.h"
#elif __has_include(<cjson/cJSON.h>)
#include <cjson/cJSON.h>
#else
#error "cJSON header not found: add vendor/cjson/cJSON.h or install libcjson-dev"
#endif

#include <errno.h>
#include <libgen.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

static char *read_file_all(const char *path, size_t *size_out) {
    if (size_out) *size_out = 0;

    FILE *fp = fopen(path, "rb");
    if (!fp) return NULL;

    if (fseek(fp, 0, SEEK_END) != 0) {
        fclose(fp);
        return NULL;
    }

    long sz = ftell(fp);
    if (sz < 0) {
        fclose(fp);
        return NULL;
    }

    if (fseek(fp, 0, SEEK_SET) != 0) {
        fclose(fp);
        return NULL;
    }

    char *buf = (char *)malloc((size_t)sz + 1);
    if (!buf) {
        fclose(fp);
        return NULL;
    }

    size_t nread = fread(buf, 1, (size_t)sz, fp);
    fclose(fp);
    if (nread != (size_t)sz) {
        free(buf);
        return NULL;
    }

    buf[nread] = 0;
    if (size_out) *size_out = nread;
    return buf;
}

static int write_file_all(const char *path, const char *data, size_t size) {
    FILE *fp = fopen(path, "wb");
    if (!fp) return -1;

    size_t nw = fwrite(data, 1, size, fp);
    fclose(fp);
    return nw == size ? 0 : -1;
}

static int ensure_parent_dir(const char *path) {
    char tmp[4096];
    size_t n = strlen(path);
    if (n + 1 > sizeof(tmp)) return -1;

    strcpy(tmp, path);
    char *parent = dirname(tmp);
    if (!parent || strcmp(parent, ".") == 0) return 0;

    struct stat st;
    if (stat(parent, &st) == 0) {
        return S_ISDIR(st.st_mode) ? 0 : -1;
    }

    if (mkdir(parent, 0755) == 0) return 0;
    return errno == EEXIST ? 0 : -1;
}

static int process_json_file(const char *in_path, const char *out_path) {
    if (!in_path || !out_path) return -1;

    size_t json_size = 0;
    char *json = read_file_all(in_path, &json_size);
    if (!json) {
        fprintf(stderr, "read failed: %s\n", strerror(errno));
        return -1;
    }

    cJSON *root = cJSON_Parse(json);
    if (!root) {
        free(json);
        fprintf(stderr, "invalid JSON\n");
        return -1;
    }

    cJSON *contenuto_item = cJSON_GetObjectItemCaseSensitive(root, "contenuto");
    if (!cJSON_IsString(contenuto_item) || !contenuto_item->valuestring) {
        cJSON_Delete(root);
        free(json);
        fprintf(stderr, "missing/invalid contenuto\n");
        return -1;
    }

    char *cleaned = clean_text_utf8(contenuto_item->valuestring);
    if (!cleaned) {
        cJSON_Delete(root);
        free(json);
        fprintf(stderr, "clean_text failed\n");
        return -1;
    }

    cJSON *new_str = cJSON_CreateString(cleaned);
    free(cleaned);
    if (!new_str) {
        cJSON_Delete(root);
        free(json);
        fprintf(stderr, "alloc failed\n");
        return -1;
    }

    cJSON_ReplaceItemInObjectCaseSensitive(root, "contenuto", new_str);

    char *out_json = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    free(json);

    if (!out_json) {
        fprintf(stderr, "serialize failed\n");
        return -1;
    }

    if (ensure_parent_dir(out_path) != 0) {
        free(out_json);
        fprintf(stderr, "cannot create output directory\n");
        return -1;
    }

    size_t out_size = strlen(out_json);
    if (write_file_all(out_path, out_json, out_size) != 0) {
        free(out_json);
        fprintf(stderr, "write failed: %s\n", strerror(errno));
        return -1;
    }

    free(out_json);
    return 0;
}

static int process_text_to_stdout(const char *text) {
    if (!text) return -1;

    char *cleaned = clean_text_utf8(text);
    if (!cleaned) {
        fprintf(stderr, "clean_text failed\n");
        return -1;
    }

    fputs(cleaned, stdout);
    fputc('\n', stdout);
    free(cleaned);
    return 0;
}

static char *read_stdin_all(void) {
    size_t cap = 4096;
    size_t len = 0;
    char *buf = (char *)malloc(cap);
    if (!buf) return NULL;

    int ch;
    while ((ch = fgetc(stdin)) != EOF) {
        if (len + 1 >= cap) {
            size_t new_cap = cap * 2;
            char *tmp = (char *)realloc(buf, new_cap);
            if (!tmp) {
                free(buf);
                return NULL;
            }
            buf = tmp;
            cap = new_cap;
        }
        buf[len++] = (char)ch;
    }

    buf[len] = 0;
    return buf;
}

int main(int argc, char **argv) {
    if (argc == 4 && strcmp(argv[1], "--process-file") == 0) {
        return process_json_file(argv[2], argv[3]) == 0 ? 0 : 1;
    }

    if (argc == 3 && strcmp(argv[1], "--clean-text") == 0) {
        return process_text_to_stdout(argv[2]) == 0 ? 0 : 1;
    }

    if (argc == 2 && strcmp(argv[1], "--clean-stdin") == 0) {
        char *input = read_stdin_all();
        if (!input) {
            fprintf(stderr, "stdin read failed\n");
            return 1;
        }

        int rc = process_text_to_stdout(input);
        free(input);
        return rc == 0 ? 0 : 1;
    }

    fprintf(stderr,
            "Uso:\n"
            "  %s --process-file <input_json> <output_json>\n"
            "  %s --clean-text <testo>\n"
            "  %s --clean-stdin\n",
            argv[0], argv[0], argv[0]);
    return 1;
}
