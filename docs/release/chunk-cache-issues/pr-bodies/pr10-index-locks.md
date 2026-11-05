# PR 10 body draft: ChunkReuse: chunk index, store locks, server ledger and store registry

> DRAFT, not pushed, not opened. Branch `pr/chunkreuse-index` (local, worktree `C:\Development\dotLLM\.claude\worktrees\pr10`): commit
> `52a036bf` plus the merge of `dev` `fa9b72ec` (which contains #1646) = head `81465ddc`. Verified on that head: Windows, Linux Docker, mutants.
> Needs James's explicit push go; route push/merge through dotllm-93.

## Title

ChunkReuse: chunk index, store locks, server ledger and store registry

## Body

Refs #1542. Follows #1577 (core), #1588 (store), #1646 (`.CSharp`).

### Summary

The chunk index and the file-based coordination around the store, in `DotLLM.ChunkReuse`. The plan had these as two PRs (index; locks, ledger,
registry) but they cannot build apart in one assembly (`ChunkIndex` calls `ServerLedger.ReadKeys`, `StoreRegistry` and `StoreLockHandle`, which
call back into `ChunkIndex`), so it is one PR.

- **`ChunkIndex`** (+ `ChunkIndex.Naming`, `ChunkRef`): per-source-file chunk lists with store keys and wire eligibility, incremental update (an edit
  re-keys only the chunks whose tokens changed), persisted as JSON next to the store, one file per chunker, model, producer and namespace
  (`index-<chunker>.<model12>.<producer8>.<namespace>.json`), legacy-name migration, status, orphan / referenced-key queries.
- **Locks**: `StoreLockHandle`, `LockingChunkStore` (puts under the store lock), `ChunkIndex.AcquireStoreLock` / `AcquireIndexLock`, `StoreOwnerLock`
  (the sole-writer ownership file for a store root; used by the server writer and the offline CLI in later PRs).
- **`ServerLedger`**: the server's record of the entries it wrote (`ledger-server.json`), so eviction never treats them as orphans.
- **`StoreRegistry`**: an advisory list of the index files in a store (`chunkcache.json`), never authoritative.
- **`Tooling/PathGlob`**: relative-path globs for the ledger / selection rules (never match outside the root).
- Cross-references (`<see cref>`) in `FileChunkStore`, `ChunkStoreBusyException`, `StoredContextAssembler`, `ChunkNamespace` restored now that their targets exist.

### Threat / concurrency note

**Locks (all exclusive `FileShare.None` lock files; never deleted: an existing file is not a held lock, only an open handle is).**

| Lock | File | Protects | Held for |
|---|---|---|---|
| Index lock | `index-...<ns>.lock` per index | the read-modify-write of ONE index (two writers would lose each other's update: last rename wins) | `Load` through `Save` of an index-only update |
| Store lock | `.chunkstore.lock` per store | store mutations that must be atomic with their bookkeeping: one put batch (+ ledger row + ledger save), one registry save, one whole eviction pass | short scopes only; never while encoding |
| Owner lock | `.chunkstore.owner.lock` | says WHO the sole writer of a root is (a second server refuses to start, an offline CLI refuses to write); not a mutex for writes | the writing server's lifetime |

- **Order**: index lock, then store lock; never an index lock while this execution flow holds the store lock of the same root (throws
  `InvalidOperationException`, enforced per flow via `AsyncLocal`; handles acquired in a child flow and handed back are not seen, documented).
- **Publication rule**: a writer saves its index (under the index lock) BEFORE putting the entries it references, and decides which referenced entries
  are already stored under the store lock AFTER that save; an eviction pass that started earlier has finished and later passes read the new index.
  The worst outcome of any race is a miss that is encoded again, never a corrupt or wrongly-deleted referenced entry.
- **Crash / stale-lock recovery**: no stale locks exist: the OS releases a dead process's handle (verified on Windows/NTFS; on Linux/macOS .NET
  emulates `FileShare.None` with advisory `flock`, released by the kernel on exit, honoured by other .NET processes only, off when
  `DOTNET_SYSTEM_IO_DISABLEFILELOCKING` is set; network file systems unsupported). A lock timeout is `ChunkStoreLockTimeoutException` (a
  `ChunkStoreBusyException`). Index and ledger saves write a temp file, flush and rename in one step: readers see the old or the new file, a crash
  leaves at most a temp file nobody reads (the ledger sweeps them after an hour). An unreadable registry is copied to `chunkcache.json.bad-<utc>` before
  being replaced; a registry of a NEWER format is never overwritten.
- **Fail closed on the ledger**: an unreadable ledger (not JSON, unknown version, malformed or duplicate row, a directory at its path, an I/O error
  other than "not found") throws `LedgerUnreadableException` and eviction deletes nothing; it is never read as empty (the server's entries would look like orphans).
- **Windows vs POSIX**: on Windows a rename over a file another handle has open is refused, so `Save` retries for up to 2 s and then throws with the old
  file intact; on POSIX `rename(2)` replaces the entry under an open reader at once and the reader keeps the old inode. Tests assert each OS's contract
  (no skip, no retry-and-hope), including the one the first Linux run caught.
- **Paths / traversal**: index paths are normalised (`\` to `/`, `.` and repeated separators dropped) and rooted paths, drive / UNC forms and `..`
  segments are rejected (`ArgumentException`); `PathGlob` rejects rooted / `..` patterns and never matches a path outside the root; file names under the
  store are built from validated parts only (chunker name, namespace validated, model and producer as lower-case hex tags; the parser rejects upper-case).
  Store entry files are named by their hex key. **Symlinks / junctions**: nothing here walks the file system for sources (`ChunkIndex.Update` takes
  `SourceFile`s already read by the caller), so link-following is the caller's concern (the corpus loader, `.CSharp`; the CLI loader, later PR). The index only ever opens
  `<storeRoot>/index-*.json`, the lock files, `ledger-server.json`, `chunkcache.json` and key-named entry files.
- **Permissions**: none are set. Files are created with the process default (umask / inherited ACL); the store directory's own permissions are the access
  control, and a store holds token ids and K/V rows (and relative source paths in the ledger / indexes), i.e. derived source content.
- **Out of scope / known**: no cap on ledger size (bounded by the store budget, ~100k rows is tens of MB); case-only renames on Windows keep the first
  spelling; two instances saving the same ledger do not merge (the owner lock makes the server its only writer; the CLI never writes it).

### Scope

22 files, +5,501 lines against the `.CSharp` PR (2,698 source, 2,803 tests). Not in this PR: `ChunkDenyList` (with the CLI), the server writer / background encode
(later), the CLI. `StoreOwnerLock` was not in the original plan but belongs with `StoreLockTests`.

### Testing

- Windows: `ChunkReuse` + `Server.ChunkCache` unit tests 591 passed / 0 failed / 1 skipped (merged head).
- Linux Docker (non-root, CI filter, `git archive` of the merged head): 586 passed / 0 failed / 6 skipped.
- Mutants on fresh archive copies: the original lock / ledger / registry / naming scripts: 59 killed, no survivor except one real gap (name parser
  accepted an upper-case model tag; fixed, test added); 12 stale-anchor mutants rewritten for the current code plus 5 new: 16 / 17 killed, the survivor
  (released handles still counted in the per-flow store-lock list) is behaviour-equivalent (every reader filters on `IsHeld`; it only changes how many
  released handles an `AsyncLocal` array keeps).
- Tests added after the first Linux run and the mutants: per-OS assertion in `Save_WhileAReaderHoldsTheIndex_Succeeds`; non-BMP / non-ASCII text and path
  (escapes plus a control assertion that the escape arrived; offsets as UTF-16, save/load round trip); lock isolation across namespace / chunker / model / producer;
  upper-case model tag rejected by the name parser.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
