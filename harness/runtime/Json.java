import java.lang.reflect.Array;
import java.math.BigDecimal;
import java.math.BigInteger;
import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Minimal JSON parse/stringify used to enforce the harness I/O contract on the
 * Java side (the JDK has no JSON library). The harness copies this file next to
 * every Java program it builds, so programs call Json.parse / Json.stringify
 * without defining them.
 *
 * Mapping: array -> List<Object>, object -> Map<String,Object> (insertion
 * order kept), string -> String, integer -> Long (BigInteger if it overflows),
 * other numbers -> Double, true/false -> Boolean, null -> null.
 */
public final class Json {
    private final String s;
    private int i;

    private Json(String s) {
        this.s = s;
    }

    // ------------------------------------------------------------------ parse

    public static Object parse(String text) {
        Json p = new Json(text);
        p.ws();
        Object v = p.value();
        p.ws();
        if (p.i != p.s.length()) throw p.err("trailing data");
        return v;
    }

    private Object value() {
        if (i >= s.length()) throw err("unexpected end of input");
        char c = s.charAt(i);
        switch (c) {
            case '{': return object();
            case '[': return array();
            case '"': return string();
            case 't': literal("true"); return Boolean.TRUE;
            case 'f': literal("false"); return Boolean.FALSE;
            case 'n': literal("null"); return null;
            default: return number();
        }
    }

    private Map<String, Object> object() {
        Map<String, Object> m = new LinkedHashMap<>();
        expect('{');
        ws();
        if (peek('}')) { i++; return m; }
        while (true) {
            ws();
            String key = string();
            ws();
            expect(':');
            ws();
            m.put(key, value());
            ws();
            if (peek(',')) { i++; continue; }
            expect('}');
            return m;
        }
    }

    private List<Object> array() {
        List<Object> a = new ArrayList<>();
        expect('[');
        ws();
        if (peek(']')) { i++; return a; }
        while (true) {
            ws();
            a.add(value());
            ws();
            if (peek(',')) { i++; continue; }
            expect(']');
            return a;
        }
    }

    private String string() {
        expect('"');
        StringBuilder sb = new StringBuilder();
        while (true) {
            if (i >= s.length()) throw err("unterminated string");
            char c = s.charAt(i++);
            if (c == '"') return sb.toString();
            if (c != '\\') { sb.append(c); continue; }
            if (i >= s.length()) throw err("bad escape");
            char e = s.charAt(i++);
            switch (e) {
                case '"': case '\\': case '/': sb.append(e); break;
                case 'b': sb.append('\b'); break;
                case 'f': sb.append('\f'); break;
                case 'n': sb.append('\n'); break;
                case 'r': sb.append('\r'); break;
                case 't': sb.append('\t'); break;
                case 'u':
                    if (i + 4 > s.length()) throw err("bad \\u escape");
                    sb.append((char) Integer.parseInt(s.substring(i, i + 4), 16));
                    i += 4;
                    break;
                default: throw err("bad escape \\" + e);
            }
        }
    }

    private Object number() {
        int start = i;
        boolean isFloat = false;
        if (peek('-')) i++;
        while (i < s.length() && Character.isDigit(s.charAt(i))) i++;
        if (peek('.')) {
            isFloat = true;
            i++;
            while (i < s.length() && Character.isDigit(s.charAt(i))) i++;
        }
        if (peek('e') || peek('E')) {
            isFloat = true;
            i++;
            if (peek('+') || peek('-')) i++;
            while (i < s.length() && Character.isDigit(s.charAt(i))) i++;
        }
        String t = s.substring(start, i);
        if (t.isEmpty() || t.equals("-")) throw err("unexpected character");
        if (isFloat) return Double.parseDouble(t);
        try {
            return Long.parseLong(t);
        } catch (NumberFormatException overflow) {
            return new BigInteger(t);
        }
    }

    private void literal(String word) {
        if (!s.startsWith(word, i)) throw err("expected " + word);
        i += word.length();
    }

    private void ws() {
        while (i < s.length() && Character.isWhitespace(s.charAt(i))) i++;
    }

    private boolean peek(char c) {
        return i < s.length() && s.charAt(i) == c;
    }

    private void expect(char c) {
        if (!peek(c)) throw err("expected '" + c + "'");
        i++;
    }

    private IllegalArgumentException err(String msg) {
        return new IllegalArgumentException("JSON parse error at offset " + i + ": " + msg);
    }

    // -------------------------------------------------------------- stringify

    public static String stringify(Object v) {
        StringBuilder sb = new StringBuilder();
        write(sb, v);
        return sb.toString();
    }

    private static void write(StringBuilder sb, Object v) {
        if (v == null) {
            sb.append("null");
        } else if (v instanceof Boolean) {
            sb.append(v.toString());
        } else if (v instanceof Double || v instanceof Float) {
            double d = ((Number) v).doubleValue();
            if (Double.isNaN(d) || Double.isInfinite(d)) {
                throw new IllegalArgumentException("NaN/Infinity is not valid JSON");
            }
            sb.append(Double.toString(d));
        } else if (v instanceof BigDecimal) {
            sb.append(((BigDecimal) v).toString());
        } else if (v instanceof Number) {  // Byte, Short, Integer, Long, BigInteger
            sb.append(v.toString());
        } else if (v instanceof CharSequence || v instanceof Character) {
            quote(sb, v.toString());
        } else if (v instanceof Map) {
            sb.append('{');
            boolean first = true;
            for (Map.Entry<?, ?> e : ((Map<?, ?>) v).entrySet()) {
                if (!first) sb.append(',');
                first = false;
                quote(sb, String.valueOf(e.getKey()));
                sb.append(':');
                write(sb, e.getValue());
            }
            sb.append('}');
        } else if (v instanceof Collection) {
            sb.append('[');
            boolean first = true;
            for (Object o : (Collection<?>) v) {
                if (!first) sb.append(',');
                first = false;
                write(sb, o);
            }
            sb.append(']');
        } else if (v.getClass().isArray()) {  // int[], long[], double[], Object[], ...
            sb.append('[');
            int n = Array.getLength(v);
            for (int k = 0; k < n; k++) {
                if (k > 0) sb.append(',');
                write(sb, Array.get(v, k));
            }
            sb.append(']');
        } else {
            throw new IllegalArgumentException("cannot serialize " + v.getClass().getName());
        }
    }

    private static void quote(StringBuilder sb, String str) {
        sb.append('"');
        for (int k = 0; k < str.length(); k++) {
            char c = str.charAt(k);
            switch (c) {
                case '"': sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                case '\b': sb.append("\\b"); break;
                case '\f': sb.append("\\f"); break;
                default:
                    if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                    else sb.append(c);
            }
        }
        sb.append('"');
    }
}
