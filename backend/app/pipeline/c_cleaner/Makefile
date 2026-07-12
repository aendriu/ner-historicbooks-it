CC = gcc
CFLAGS = -O2 -Wall -Wextra
LDFLAGS = -lm

SRC_DIR = src
BIN_DIR = bin
DATA_DIR = data

TARGET = $(BIN_DIR)/ocr_cleaner
SRCS = $(SRC_DIR)/ocr_cleaner.c $(SRC_DIR)/cJSON.c
OBJS = $(SRCS:.c=.o)

.PHONY: all clean run

all: $(TARGET)

$(TARGET): $(OBJS)
	@mkdir -p $(BIN_DIR)
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)

$(SRC_DIR)/%.o: $(SRC_DIR)/%.c
	$(CC) $(CFLAGS) -c -o $@ $<

run: $(TARGET)
	@mkdir -p $(DATA_DIR)/metadata_cleaned
	./$(TARGET) $(DATA_DIR)/metadata $(DATA_DIR)/metadata_cleaned

clean:
	rm -f $(SRC_DIR)/*.o $(TARGET)
