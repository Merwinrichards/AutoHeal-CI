def fix_pipeline(log):
    if "command not found" in log:
        return {
            "issue": "Invalid command used",
            "fix_yaml": """stages:
  - build

build-job:
  stage: build
  script:
    - echo "Building..."
    - echo "Fixed"
""",
            "explanation": "Removed invalid command and replaced with safe execution",
            "status": "Auto-Fix Ready"
        }
    else:
        return {
            "issue": "No issue",
            "fix_yaml": "No changes needed",
            "explanation": "Pipeline is fine",
            "status": "OK"
        }


# simulate GitLab log
log = "invalid_command_here: command not found"

result = fix_pipeline(log)

print("\n🚨 Pipeline Failure Detected")
print("Issue:", result["issue"])

print("\n🛠️ Suggested Fix YAML:\n")
print(result["fix_yaml"])

print("\n💡 Explanation:", result["explanation"])
print("Status:", result["status"])

with open(".gitlab-ci-fixed.yml", "w") as f:
    f.write(result["fix_yaml"])

print("\n✅ Fixed CI file generated: .gitlab-ci-fixed.yml")