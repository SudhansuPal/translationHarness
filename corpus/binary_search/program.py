import json
import sys


def binary_search(items, target):
    lo = 0
    hi = len(items) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if items[mid] == target:
            return mid
        if items[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1


def main():
    data = json.load(sys.stdin)
    print(json.dumps(binary_search(data[0], data[1])))


if __name__ == "__main__":
    main()
