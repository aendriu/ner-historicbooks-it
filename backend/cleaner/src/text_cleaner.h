#pragma once

#include <stddef.h>

// Cleans UTF-8 input text and returns a newly allocated UTF-8 string.
// Caller must free() the returned pointer.
char *clean_text_utf8(const char *input_utf8);
