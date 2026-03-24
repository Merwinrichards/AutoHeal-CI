# AutoHeal CI

AutoHeal CI is a Python project that analyzes CI/CD failure logs and generates a corrected GitLab pipeline file. It is designed for practical recovery workflows where a broken pipeline should be diagnosed, repaired, validated, and written safely.

The core engine is built around the Google Gemini API through the 2026 SDK (google-genai) with local fallback behavior when API quota is exhausted or unavailable.

## Project Goals

- Turn raw pipeline logs into structured diagnosis (issue + root cause + fix).
- Generate a valid GitLab CI YAML candidate from AI output.
- Prevent bad writes to production pipeline files.
- Keep working even when Gemini is rate-limited (429 RESOURCE_EXHAUSTED).

## Main Workflow

1. Read input log from file, CLI text, or interactive prompt.
2. Build a structured DevOps prompt.
3. Call Gemini model gemini-2.0-flash.
4. Parse AI response into Issue, Explanation, and Fix.
5. Extract YAML, validate it, and optionally repair it with a YAML-only retry prompt.
6. Write report JSON and safe output YAML files.
7. Atomically replace .gitlab-ci.yml only after validation checks pass.

## Core Components

- ai_fixer.py
  Main engine and CLI entry point.

  Key responsibilities:
  - Prompt construction.
  - Gemini API call with retry and exponential backoff.
  - Markdown-tolerant parsing of Issue/Explanation/Fix sections.
  - YAML extraction and validation with PyYAML.
  - Atomic write, backup creation, and post-write verification.
  - Structured report generation.

- auto_fix_gitlab.py
  GitLab API automation helper.

  Key responsibilities:
  - Push generated CI YAML to repository file.
  - Trigger a pipeline run.
  - Query latest pipeline status.

- dashboard.py
  Streamlit UI for interactive usage and visualization.

  Notes:
  - Includes local analysis and Gemini comparison UI sections.
  - Includes GitLab automation buttons and judge-mode export.

- validate_fixes.py, demo_fixes.py, debug_timeout.py
  Utility and demonstration scripts for behavior checks.

## Current Stable Path

For production use in this repository, prefer the direct CLI flow through ai_fixer.py and optional GitLab automation via auto_fix_gitlab.py.

## Requirements

- Python 3.12+
- Windows PowerShell (or any shell with equivalent commands)
- Dependencies listed in requirements.txt

Install dependencies:

```bash
pip install -r requirements.txt
```

## Environment Variables

Gemini:

- GEMINI_API_KEY

GitLab automation:

- GITLAB_TOKEN
- GITLAB_PROJECT_ID
- GITLAB_BRANCH (optional, default: main)
- GITLAB_API_BASE (optional, default: https://gitlab.com/api/v4)

PowerShell example:

```powershell
$env:GEMINI_API_KEY = "YOUR_API_KEY"
$env:GITLAB_TOKEN = "YOUR_GITLAB_TOKEN"
$env:GITLAB_PROJECT_ID = "12345678"
```

## Usage

### 1) Analyze and Generate Fix

Interactive log input:

```bash
python ai_fixer.py
```

Inline log text:

```bash
python ai_fixer.py --log-text "ERROR: Job failed: npm: command not found"
```

Log file input:

```bash
python ai_fixer.py --log-file sample.log
```

Custom output paths:

```bash
python ai_fixer.py --log-file sample.log --report ai_report.json --fixed-ci .gitlab-ci-fixed.yml
```

### 2) Push Fix to GitLab and Trigger Pipeline

```bash
python auto_fix_gitlab.py --ci-file .gitlab-ci-fixed.yml --target-file .gitlab-ci.yml
```

### 3) Check Latest Pipeline Status

```bash
python auto_fix_gitlab.py --status-only
```

### 4) Launch Dashboard

```bash
streamlit run dashboard.py
```

## Output Files

- .gitlab-ci-fixed.yml
  Secondary generated YAML artifact.

- .gitlab-ci.yml
  Canonical target file updated through safe write logic.

- .gitlab-ci.yml.YYYYMMDD_HHMMSS.bak
  Automatic backup created before overwrite.

- ai_report.json
  Structured analysis output and runtime status.

- judge_mode_snapshot.json / judge_mode_snapshot.md
  Dashboard comparison exports when judge mode is used.

## Reliability and Safety Features

### Gemini Retry and Quota Handling

- Retries transient quota/rate-limit failures with exponential backoff.
- Detects common quota signatures such as 429 and RESOURCE_EXHAUSTED.
- Falls back to a local response when retries fail or API key is missing.

### Response Parsing Robustness

- Normalizes heading variants into Issue, Explanation, and Fix.
- Handles common markdown styles such as bold headers, list prefixes, and heading markers.
- Falls back to first YAML fenced block extraction when needed.

### YAML Safety

- Rejects invalid YAML before writing.
- Writes via temporary file + atomic replace.
- Re-validates file after write.
- Restores backup if post-write verification fails.

## Prompt Contract

The analyzer expects AI output in this strict format:

```
Issue: <Short title of the problem>
Explanation: <Brief root cause analysis>
Fix:
```yaml
# Full corrected .gitlab-ci.yml content only
```
```

Key requirements:
- Issue must be a short, actionable title.
- Explanation must be 1-2 sentences of root cause analysis.
- Fix must be a valid, complete .gitlab-ci.yml wrapped in triple backticks with yaml language marker.
- No additional text after the closing backticks.

If the Fix section is not valid YAML or missing backtick fencing, the system sends a second YAML-only repair prompt.

## Repository Layout

- ai_fixer.py: core analyzer and fixer
- auto_fix_gitlab.py: GitLab API integration
- dashboard.py: Streamlit UI
- validate_fixes.py: quick fix-generation validation
- demo_fixes.py: demonstration scenarios
- debug_timeout.py: timeout test helper
- requirements.txt: Python dependencies
- sample_logs.json, batch_test.json: sample/test data
- ai_report.json, batch_eval_report.json: generated reports

## Troubleshooting

### Missing GEMINI_API_KEY

- Behavior: local fallback is used.
- Action: set GEMINI_API_KEY in your shell or CI secret store.

### Frequent 429 or RESOURCE_EXHAUSTED

- Behavior: automatic retries with backoff, then fallback.
- Action: reduce request frequency, rotate to paid quota, or cache repeated analyses.

### Invalid YAML Generated

- Behavior: one YAML-only repair pass is attempted.
- Action: inspect ai_report.json and generated YAML for prompt/context improvements.

### GitLab API Failures

- Check token scope and project ID.
- Verify branch permissions.
- Confirm API base URL for self-hosted GitLab instances.

## Security Notes

- Do not hardcode API tokens in source files.
- Use CI secret variables for GEMINI_API_KEY and GitLab tokens.
- Review generated .gitlab-ci.yml before committing in sensitive repos.

## Future Improvements

- Add configurable retry settings through CLI flags.
- Add automated schema checks for generated pipeline structure.
- Expand deterministic local fallback templates by error category.
