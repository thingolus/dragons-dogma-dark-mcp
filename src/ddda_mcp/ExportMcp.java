// Based on Thingolus/project contributors' ExportResearch.java (MIT).
// @category DDDA
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import ghidra.program.model.address.AddressIterator;
import java.util.ArrayList;
import java.util.List;
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
            List<String> references = new ArrayList<>();
            ReferenceIterator incoming = currentProgram.getReferenceManager().getReferencesTo(function.getEntryPoint());
            boolean refsTruncated = false;
            while (incoming.hasNext()) {
                Reference ref = incoming.next();
                if (references.size() >= 128) { refsTruncated = true; break; }
                Function owner = getFunctionContaining(ref.getFromAddress());
                references.add("{\"direction\":\"incoming\",\"from\":" + quote(ref.getFromAddress().toString())
                    + ",\"to\":" + quote(ref.getToAddress().toString()) + ",\"type\":" + quote(ref.getReferenceType().toString())
                    + ",\"function\":" + (owner == null ? "null" : quote(owner.getName())) + "}");
            }
            AddressIterator sites = currentProgram.getReferenceManager().getReferenceSourceIterator(function.getBody(), true);
            int examined = 0;
            while (sites.hasNext()) {
                if (++examined > 4096 || references.size() >= 256) { refsTruncated = true; break; }
                for (Reference ref : currentProgram.getReferenceManager().getReferencesFrom(sites.next())) {
                    if (!ref.getReferenceType().isCall()) continue;
                    Function target = getFunctionContaining(ref.getToAddress());
                    references.add("{\"direction\":\"outgoing_call\",\"from\":" + quote(ref.getFromAddress().toString())
                        + ",\"to\":" + quote(ref.getToAddress().toString()) + ",\"type\":" + quote(ref.getReferenceType().toString())
                        + ",\"function\":" + (target == null ? "null" : quote(target.getName())) + "}");
                    if (references.size() >= 256) { refsTruncated = true; break; }
                }
            }
            String json = "{\"success\":true,\"game_sha256\":" + quote(hash.toLowerCase())
                + ",\"function\":" + quote(function.getName()) + ",\"address\":" + quote(function.getEntryPoint().toString())
                + ",\"truncated\":" + truncated + ",\"code\":" + quote(code)
                + ",\"references_truncated\":" + refsTruncated + ",\"references\":[" + String.join(",", references) + "]}";
            Files.writeString(Path.of(args[0]), json, StandardCharsets.UTF_8);
        } finally { decomp.dispose(); }
    }
}
