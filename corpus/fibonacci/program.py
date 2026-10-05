import json
import sys


def fibonacci(n):
    seq = []
    a, b = 0, 1
    for _ in range(n):
        seq.append(a)
        a, b = b, a + b
    return seq


def main():
    data = json.load(sys.stdin)
    print(json.dumps(fibonacci(data[0])))


if __name__ == "__main__":
    main()
