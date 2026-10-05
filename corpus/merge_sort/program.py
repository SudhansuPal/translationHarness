import json
import sys


def merge(left, right):
    result = []
    i = 0
    j = 0
    while i < len(left) and j < len(right):
        if left[i] <= right[j]:
            result.append(left[i])
            i += 1
        else:
            result.append(right[j])
            j += 1
    result.extend(left[i:])
    result.extend(right[j:])
    return result


def merge_sort(items):
    if len(items) <= 1:
        return list(items)
    mid = len(items) // 2
    return merge(merge_sort(items[:mid]), merge_sort(items[mid:]))


def main():
    data = json.load(sys.stdin)
    print(json.dumps(merge_sort(data)))


if __name__ == "__main__":
    main()
