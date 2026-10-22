// Based on Thingolus/project contributors' ExportResearch.java (MIT).
// @category DDDA
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Function;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

public class ExportMcp extends GhidraScript {
    private String quote(String value) {
        StringBuilder out = new StringBuilder("\"");
        for (char c : value.toCharArray()) {
            if (c == '"' || c == '\\') out.append('\\').append(c);
            else if (c < 32) out.append(String.format("\\u%04x", (int)c));
            else out.append(c);
        }
        return out.append('"').toString();
    }
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 3) throw new IllegalArgumentException("output, expected hash, VA required");
        String hash = currentProgram.getExecutableSHA256();
        if (hash == null || !hash.equalsIgnoreCase(args[1])) throw new IllegalStateException("Database executable hash mismatch");
        Function function = getFunctionContaining(toAddr(args[2]));
        if (function == null) throw new IllegalStateException("No analyzed function at symbol");
        DecompInterface decomp = new DecompInterface();
        try {
            if (!decomp.openProgram(currentProgram)) throw new IllegalStateException("Cannot open decompiler");
            DecompileResults result = decomp.decompileFunction(function, 45, monitor);
            if (!result.decompileCompleted()) throw new IllegalStateException(result.getErrorMessage());
            String code = result.getDecompiledFunction().getC();
            boolean truncated = code.length() > 200000;
            if (truncated) code = code.substring(0,200000);
            String json = "{\"success\":true,\"game_sha256\":" + quote(hash.toLowerCase())
                + ",\"function\":" + quote(function.getName()) + ",\"address\":" + quote(function.getEntryPoint().toString())
                + ",\"truncated\":" + truncated + ",\"code\":" + quote(code) + "}";
            Files.writeString(Path.of(args[0]), json, StandardCharsets.UTF_8);
        } finally { decomp.dispose(); }
    }
}
