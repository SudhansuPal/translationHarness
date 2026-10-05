import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class Main {
    private static final String PUNCTUATION = ".,!?;:\"'()";

    static String strip(String word) {
        int start = 0;
        int end = word.length();
        while (start < end && PUNCTUATION.indexOf(word.charAt(start)) >= 0) {
            start++;
        }
        while (end > start && PUNCTUATION.indexOf(word.charAt(end - 1)) >= 0) {
            end--;
        }
        return word.substring(start, end);
    }

    static Map<String, Long> wordCount(String text) {
        Map<String, Long> counts = new LinkedHashMap<>();
        for (String raw : text.toLowerCase().trim().split("\\s+")) {
            String word = strip(raw);
            if (!word.isEmpty()) {
                counts.merge(word, 1L, Long::sum);
            }
        }
        return counts;
    }

    public static void main(String[] args) throws IOException {
        String input = new String(System.in.readAllBytes(), StandardCharsets.UTF_8);
        List<?> data = (List<?>) Json.parse(input);
        System.out.println(Json.stringify(wordCount((String) data.get(0))));
    }
}
