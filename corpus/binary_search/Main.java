import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.List;

public class Main {
    static long binarySearch(List<?> items, long target) {
        int lo = 0;
        int hi = items.size() - 1;
        while (lo <= hi) {
            int mid = (lo + hi) / 2;
            long value = (Long) items.get(mid);
            if (value == target) {
                return mid;
            }
            if (value < target) {
                lo = mid + 1;
            } else {
                hi = mid - 1;
            }
        }
        return -1;
    }

    public static void main(String[] args) throws IOException {
        String input = new String(System.in.readAllBytes(), StandardCharsets.UTF_8);
        List<?> data = (List<?>) Json.parse(input);
        System.out.println(Json.stringify(binarySearch((List<?>) data.get(0), (Long) data.get(1))));
    }
}
