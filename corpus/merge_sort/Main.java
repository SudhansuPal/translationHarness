import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

public class Main {
    static List<Long> merge(List<Long> left, List<Long> right) {
        List<Long> result = new ArrayList<>();
        int i = 0;
        int j = 0;
        while (i < left.size() && j < right.size()) {
            if (left.get(i) <= right.get(j)) {
                result.add(left.get(i));
                i++;
            } else {
                result.add(right.get(j));
                j++;
            }
        }
        result.addAll(left.subList(i, left.size()));
        result.addAll(right.subList(j, right.size()));
        return result;
    }

    static List<Long> mergeSort(List<Long> items) {
        if (items.size() <= 1) {
            return new ArrayList<>(items);
        }
        int mid = items.size() / 2;
        return merge(mergeSort(items.subList(0, mid)), mergeSort(items.subList(mid, items.size())));
    }

    public static void main(String[] args) throws IOException {
        String input = new String(System.in.readAllBytes(), StandardCharsets.UTF_8);
        List<?> raw = (List<?>) Json.parse(input);
        List<Long> data = new ArrayList<>();
        for (Object o : raw) {
            data.add((Long) o);
        }
        System.out.println(Json.stringify(mergeSort(data)));
    }
}
