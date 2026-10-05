import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

public class Main {
    static List<Long> fibonacci(long n) {
        List<Long> seq = new ArrayList<>();
        long a = 0;
        long b = 1;
        for (long i = 0; i < n; i++) {
            seq.add(a);
            long next = a + b;
            a = b;
            b = next;
        }
        return seq;
    }

    public static void main(String[] args) throws IOException {
        String input = new String(System.in.readAllBytes(), StandardCharsets.UTF_8);
        List<?> data = (List<?>) Json.parse(input);
        System.out.println(Json.stringify(fibonacci((Long) data.get(0))));
    }
}
