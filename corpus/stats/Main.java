import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class Main {
    static Map<String, Object> stats(List<?> values) {
        if (values.isEmpty()) {
            return null;
        }
        long total = 0;
        long min = Long.MAX_VALUE;
        long max = Long.MIN_VALUE;
        for (Object o : values) {
            long v = (Long) o;
            total += v;
            min = Math.min(min, v);
            max = Math.max(max, v);
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("count", (long) values.size());
        result.put("min", min);
        result.put("max", max);
        result.put("sum", total);
        result.put("mean", (double) total / values.size());
        return result;
    }

    public static void main(String[] args) throws IOException {
        String input = new String(System.in.readAllBytes(), StandardCharsets.UTF_8);
        List<?> data = (List<?>) Json.parse(input);
        System.out.println(Json.stringify(stats(data)));
    }
}
