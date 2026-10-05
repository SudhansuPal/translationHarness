import com.github.javaparser.ParserConfiguration;
import com.github.javaparser.StaticJavaParser;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.body.BodyDeclaration;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.ConstructorDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.expr.Name;
import com.github.javaparser.ast.expr.SimpleName;
import com.github.javaparser.ast.stmt.BlockStmt;
import com.github.javaparser.ast.stmt.ExplicitConstructorInvocationStmt;
import com.github.javaparser.ast.stmt.Statement;
import com.github.javaparser.printer.lexicalpreservation.LexicalPreservingPrinter;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Random;
import java.util.Set;

/**
 * Additive-only Java mutations for harness/mutate.py, done on the AST.
 *
 * Usage: java -cp javaparser-core.jar:classes JavaMutator <operator> <seed>
 * Reads Java source on stdin, writes the mutated source to stdout.
 * Operators: unused_variable, unused_function. Exit code 2 = cannot apply.
 *
 * LexicalPreservingPrinter keeps untouched code in its original layout.
 */
public final class JavaMutator {
    private final CompilationUnit cu;
    private final Random rng;
    private final Set<String> used = new HashSet<>();

    private JavaMutator(CompilationUnit cu, Random rng) {
        this.cu = cu;
        this.rng = rng;
        cu.findAll(SimpleName.class).forEach(n -> used.add(n.getIdentifier()));
        cu.findAll(Name.class).forEach(n -> used.add(n.getIdentifier()));
    }

    private String fresh(String prefix) {
        while (true) {
            String name = prefix + rng.nextInt(1_000_000);
            if (used.add(name)) return name;
        }
    }

    /** Insert `<type> <fresh> = <literal>;` before an existing statement of a random block. */
    private void unusedVariable() {
        // Inserting directly before an existing statement is always reachable
        // (that statement is reachable, or the original would not compile).
        // Appending at the end is only allowed for empty blocks, so we never
        // land after a return/throw/break/continue or an infinite loop.
        List<BlockStmt> blocks = new ArrayList<>();
        List<Integer> starts = new ArrayList<>();
        for (BlockStmt b : cu.findAll(BlockStmt.class)) {
            int start = 0;
            boolean ctorBody = b.getParentNode().filter(p -> p instanceof ConstructorDeclaration).isPresent();
            if (ctorBody && !b.getStatements().isEmpty()
                    && b.getStatement(0) instanceof ExplicitConstructorInvocationStmt) {
                start = 1; // this(...) / super(...) must stay first
            }
            int n = b.getStatements().size();
            if (start < n || n == 0) {
                blocks.add(b);
                starts.add(start);
            }
        }
        if (blocks.isEmpty()) throw new CannotApply("no block to insert into");
        int k = rng.nextInt(blocks.size());
        BlockStmt block = blocks.get(k);
        int n = block.getStatements().size();
        int index = n == 0 ? 0 : starts.get(k) + rng.nextInt(n - starts.get(k));

        String[][] typed = {
            {"int", Integer.toString(rng.nextInt(2001) - 1000)},
            {"long", (rng.nextInt(2001) - 1000) + "L"},
            {"double", (rng.nextInt(100) / 4.0) + ""},
            {"boolean", rng.nextBoolean() ? "true" : "false"},
            {"String", "\"s" + rng.nextInt(1000) + "\""},
            {"char", "'" + (char) ('a' + rng.nextInt(26)) + "'"},
        };
        String[] pick = typed[rng.nextInt(typed.length)];
        Statement decl = StaticJavaParser.parseStatement(
                pick[0] + " " + fresh("unusedVar") + " = " + pick[1] + ";");
        block.getStatements().add(index, decl);
    }

    /** Add a never-called `private static` method with a fresh name to a random class. */
    private void unusedFunction() {
        List<ClassOrInterfaceDeclaration> classes = new ArrayList<>();
        for (ClassOrInterfaceDeclaration c : cu.findAll(ClassOrInterfaceDeclaration.class)) {
            // Static members are always legal in top-level and static nested
            // classes; skip interfaces, local classes and inner classes.
            if (!c.isInterface() && !c.isLocalClassDeclaration() && (c.isTopLevelType() || c.isStatic())) {
                classes.add(c);
            }
        }
        if (classes.isEmpty()) throw new CannotApply("no class to add a method to");
        ClassOrInterfaceDeclaration cls = classes.get(rng.nextInt(classes.size()));

        String[] types = {"int", "long", "double"};
        String type = types[rng.nextInt(types.length)];
        String[] ops = {"+", "-", "*"};
        List<String> params = new ArrayList<>();
        for (int i = 0, n = 1 + rng.nextInt(3); i < n; i++) params.add(fresh("p"));

        StringBuilder sb = new StringBuilder("private static ").append(type).append(' ')
                .append(fresh("unusedFn")).append('(');
        for (int i = 0; i < params.size(); i++) {
            if (i > 0) sb.append(", ");
            sb.append(type).append(' ').append(params.get(i));
        }
        sb.append(") {\n");
        String acc = params.get(0);
        List<String> operands = new ArrayList<>(params.subList(1, params.size()));
        for (int i = 0, extra = rng.nextInt(3); i < extra; i++) operands.add(Integer.toString(1 + rng.nextInt(9)));
        for (String operand : operands) {
            String tmp = fresh("t");
            sb.append(type).append(' ').append(tmp).append(" = ").append(acc).append(' ')
                    .append(ops[rng.nextInt(ops.length)]).append(' ').append(operand).append(";\n");
            acc = tmp;
        }
        sb.append("return ").append(acc).append(";\n}");

        MethodDeclaration method = StaticJavaParser.parseMethodDeclaration(sb.toString());
        List<BodyDeclaration<?>> members = cls.getMembers();
        members.add(rng.nextInt(members.size() + 1), method);
    }

    private static final class CannotApply extends RuntimeException {
        CannotApply(String msg) {
            super(msg);
        }
    }

    public static void main(String[] args) throws IOException {
        if (args.length != 2) {
            System.err.println("usage: JavaMutator <unused_variable|unused_function> <seed>");
            System.exit(64);
        }
        StaticJavaParser.getParserConfiguration().setLanguageLevel(ParserConfiguration.LanguageLevel.JAVA_17);
        String source = new String(System.in.readAllBytes(), StandardCharsets.UTF_8);
        CompilationUnit cu = LexicalPreservingPrinter.setup(StaticJavaParser.parse(source));
        JavaMutator m = new JavaMutator(cu, new Random(Long.parseLong(args[1])));
        try {
            switch (args[0]) {
                case "unused_variable": m.unusedVariable(); break;
                case "unused_function": m.unusedFunction(); break;
                default:
                    System.err.println("unknown operator " + args[0]);
                    System.exit(64);
            }
        } catch (CannotApply e) {
            System.err.println("cannot apply " + args[0] + ": " + e.getMessage());
            System.exit(2);
        }
        String out;
        try {
            out = LexicalPreservingPrinter.print(cu);
        } catch (RuntimeException e) {
            out = cu.toString(); // layout-preserving printer has edge-case bugs; fall back
        }
        System.out.print(out);
    }
}
