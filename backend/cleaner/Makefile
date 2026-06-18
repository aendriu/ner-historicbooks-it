CC ?= gcc
CFLAGS ?= -std=c11 -O2 -Wall -Wextra -Wpedantic
LDFLAGS ?= -lm
LDLIBS ?=

SRC := src/main.c src/text_cleaner.c

CJSON_VENDOR_DIR := vendor/cjson
CJSON_VENDOR_SRC := $(CJSON_VENDOR_DIR)/cJSON.c

ifneq ("$(wildcard $(CJSON_VENDOR_SRC))","")
CFLAGS += -I$(CJSON_VENDOR_DIR)
SRC += $(CJSON_VENDOR_SRC)
else
LDLIBS += -lcjson
endif

OBJ := $(SRC:.c=.o)
BIN := preprocess_c

all: $(BIN)

$(BIN): $(OBJ)
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS) $(LDLIBS)

clean:
	rm -f $(OBJ) $(BIN)

.PHONY: all clean
