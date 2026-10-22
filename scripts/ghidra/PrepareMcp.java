// Copyright (c) 2026 Thingolus. MIT.
// @category DDDA
import ghidra.app.script.GhidraScript;
import java.nio.file.Files;
import java.nio.file.Path;

public class PrepareMcp extends GhidraScript {
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 4) throw new IllegalArgumentException("hash, VA, symbol, receipt required");
        if (!args[0].equalsIgnoreCase(currentProgram.getExecutableSHA256()))
            throw new IllegalStateException("Executable hash mismatch");
        if (!args[2].matches("[A-Za-z0-9_]+")) throw new IllegalArgumentException("Invalid symbol");
        var address = toAddr(args[1]);
        if (getFunctionAt(address) == null) {
            if (!disassemble(address)) throw new IllegalStateException("Cannot disassemble symbol");
            if (createFunction(address, args[2]) == null) throw new IllegalStateException("Cannot create function");
        }
        Files.writeString(Path.of(args[3]), "{\"success\":true,\"game_sha256\":\"" + args[0] + "\"}");
    }
}
