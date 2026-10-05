import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

public class Main {
    static List<Long> bubbleSort(List<Long> arr) {
        int n = arr.size();
        for (int i = 0; i < n; i++) {
            for (int j = 0; j < n - i - 1; j++) {
                if (arr.get(j) > arr.get(j + 1)) {
                    Long tmp = arr.get(j);
                    arr.set(j, arr.get(j + 1));
                    arr.set(j + 1, tmp);
                }
            }
        }
        return arr;
    }

    public static void main(String[] args) throws IOException {
        String input = new String(System.in.readAllBytes(), StandardCharsets.UTF_8);
        List<?> raw = (List<?>) Json.parse(input);
        List<Long> data = new ArrayList<>();
        for (Object o : raw) {
            data.add((Long) o);
        }
        System.out.println(Json.stringify(bubbleSort(data)));
    }
}
