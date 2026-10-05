import json
import sys


def word_count(text):
    counts = {}
    for word in text.lower().split():
        word = word.strip(".,!?;:\"'()")
        if word:
            counts[word] = counts.get(word, 0) + 1
    return counts


def main():
    data = json.load(sys.stdin)
    print(json.dumps(word_count(data[0])))


if __name__ == "__main__":
    main()
