from ai_fixer import analyze_pipeline_failure

log = "ERROR: Job execution timed out after 3600 seconds"
result = analyze_pipeline_failure(log)

print(f"Findings: {result['total_findings']}")
if result['detected_errors']:
    for f in result['detected_errors']:
        print(f"  - Issue: {f['issue']}")
        print(f"    Keyword: {f['keyword']}")
else:
    print("  No errors detected")

print("\nGenerated pipeline starts with:")
print(result['generated_pipeline_yaml'][:300])
