import json
import sys


def stats(values):
    if not values:
        return None
    total = sum(values)
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "sum": total,
        "mean": total / len(values),
    }


def main():
    data = json.load(sys.stdin)
    print(json.dumps(stats(data)))


if __name__ == "__main__":
    main()
