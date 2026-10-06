"""Keep throwaway directories out of pytest collection.

The 2026-10-03 fix pack left three non-source trees under the repo root:
the frozen backups made before patching and the extracted fix-pack itself.
They contain copies of the test files (including the pre-change versions),
so without this pytest would collect each test twice and run stale tests.
Only the live suite under backend/tests should be collected.
"""
collect_ignore_glob = [
    "backend_backup_2026-10-03/*",
    "mobile/lib_backup_2026-10-03/*",
    "pqf_fixes_2026-10-01/*",
]
