#!/usr/bin/env python3
"""Quick validation of fix generation for 6 error scenarios."""

from ai_fixer import analyze_pipeline_failure

print("\n" + "="*80)
print("  AutoHeal CI: Fix Generation Validation (6 Scenarios)")
print("="*80)

test_cases = [
    ("NPM ERROR", "npm ERR! 404 Not Found - GET https://registry.npmjs.org/does-not-exist", "npm ci"),
    ("PYTHON ERROR", "ModuleNotFoundError: No module named 'numpy'", "pip install -r requirements.txt"),
    ("CONNECTION ERROR", "ConnectionRefusedError: [Errno 111] Connection refused", "retry_connection"),
    ("TIMEOUT ERROR", "ERROR: Job timeout after 3600 seconds", "timeout: 15 minutes"),
    ("COMMAND ERROR", "/bin/bash: line 1: make: command not found", "check_command"),
    ("PERMISSION ERROR", "bash: ./build.sh: Permission denied", "chmod +x"),
]

passed = 0
for name, log, expected_keyword in test_cases:
    result = analyze_pipeline_failure(log)
    pipeline = result['generated_pipeline_yaml']
    
    if expected_keyword in pipeline:
        sz = len(pipeline)
        print(f"[PASS] {name:20s} - Generated pipeline ({sz} bytes)")
        passed += 1
    else:
        print(f"[FAIL] {name:20s} - Missing keyword: {expected_keyword}")
        print(f"       First 200 chars: {pipeline[:200]}")

print(f"\n{'='*80}")
print(f"Results: {passed}/6 tests passed")
print(f"{'='*80}\n")

if passed == 6:
    print("[SUCCESS] All fix generation scenarios working correctly!")
else:
    print(f"[WARNING] {6-passed} tests failed")
    exit(1)
