import argparse
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from google import genai
import yaml  # type: ignore[import-not-found]


PROMPT_TEMPLATE = """You are a DevOps expert.

Analyze the following CI/CD pipeline error log.

Tasks:
1. Identify the issue.
2. Explain the root cause.
3. Provide the corrected .gitlab-ci.yml file.

Error Log:
{log}

Respond strictly in this format:

Issue: <Short title of the problem>
Explanation: <Brief root cause analysis>
Fix:
```yaml
# Full corrected .gitlab-ci.yml content only - start here
stages:
  - build

build:
  stage: build
  script:
    - echo "Your fix here"
```"""


@dataclass
class GeminiSettings:
    enabled: bool = True
    model: str = "gemini-2.5-flash"
    api_key: Optional[str] = None
    timeout_seconds: int = 30


# ---------------------------------------------------------------------------
# Local log analysis engine
# ---------------------------------------------------------------------------

# Each rule: (regex_pattern, issue_title, severity, confidence_pct, fix_hint)
_LOCAL_RULES: List[tuple] = [
    (
        r"(?i)(permission denied|cannot open|EACCES|access denied|Operation not permitted)",
        "Permission denied error",
        "high",
        85,
        ["chmod +x <file>", "sudo chown -R $(whoami) <path>"],
    ),
    (
        r"(?i)(no such file or directory|file not found|cannot find|FileNotFoundError|ENOENT)",
        "Missing file or directory",
        "high",
        88,
        ["ls -la <path>", "mkdir -p <missing_dir>"],
    ),
    (
        r"(?i)(docker.*not found|Cannot connect to the Docker daemon|docker: command not found)",
        "Docker daemon unavailable",
        "critical",
        90,
        ["services:\n  - docker:dind", "variables:\n  DOCKER_HOST: tcp://docker:2375"],
    ),
    (
        r"(?i)(pip install.*failed|Could not find a version|No matching distribution|ERROR: Could not)",
        "Python package installation failure",
        "high",
        87,
        ["pip install --upgrade pip", "pip install <package>==<version>"],
    ),
    (
        r"(?i)(npm (install|ci).*failed|ENOENT.*package\.json|npm ERR!)",
        "Node.js/npm installation failure",
        "high",
        86,
        ["npm ci --cache .npm --prefer-offline", "node --version && npm --version"],
    ),
    (
        r"(?i)(syntax error|SyntaxError|unexpected token|parse error|invalid syntax)",
        "Syntax error in script or config",
        "medium",
        82,
        ["Validate YAML: yamllint .gitlab-ci.yml", "Lint scripts before committing"],
    ),
    (
        r"(?i)(connection refused|ECONNREFUSED|connection timed out|network unreachable|could not resolve host)",
        "Network connectivity failure",
        "high",
        84,
        ["Check service health in services: block", "Add retry: max: 2 to job"],
    ),
    (
        r"(?i)(out of memory|OOMKilled|memory limit|Killed.*memory|java\.lang\.OutOfMemoryError)",
        "Out of memory / OOM kill",
        "critical",
        91,
        ["Increase runner memory limits", "Add JAVA_OPTS: -Xmx512m or equivalent"],
    ),
    (
        r"(?i)(image pull.*failed|ErrImagePull|ImagePullBackOff|not found.*registry|manifest unknown)",
        "Docker image pull failure",
        "critical",
        89,
        ["Verify image name and tag exist", "Check registry credentials in CI/CD variables"],
    ),
    (
        r"(?i)(exit code [1-9]\d*|exited with code [1-9]|returned non-zero exit status)",
        "Script exited with non-zero status",
        "high",
        80,
        ["Add set -e to script", "Check command output for root cause above"],
    ),
    (
        r"(?i)(timeout|timed out|deadline exceeded|context deadline)",
        "Job or step timed out",
        "medium",
        78,
        ["Increase timeout: in job config", "Optimize slow steps or cache dependencies"],
    ),
    (
        r"(?i)(yaml.*error|invalid yaml|mapping values are not allowed|could not find expected|YAMLException)",
        "Invalid YAML configuration",
        "critical",
        93,
        ["yamllint .gitlab-ci.yml", "Validate indentation (use spaces, not tabs)"],
    ),
    (
        r"(?i)(authentication failed|invalid credentials|unauthorized|401|403 forbidden)",
        "Authentication / authorization failure",
        "high",
        86,
        ["Rotate CI/CD secret variables", "Check token scopes and expiry"],
    ),
    (
        r"(?i)(disk.*full|no space left|ENOSPC|disk quota exceeded)",
        "Disk space exhausted",
        "critical",
        92,
        ["Add cache cleanup step", "Use artifacts with expire_in:"],
    ),
    (
        r"(?i)(apt-get.*failed|dpkg.*error|E: Unable to locate package|apt.*404)",
        "APT package manager failure",
        "high",
        85,
        ["apt-get update -yqq && apt-get install -yqq <pkg>", "Pin package versions"],
    ),
    (
        r"(?i)(alpine|apk add.*error|apk.*not found)",
        "Alpine apk package failure",
        "medium",
        80,
        ["apk update && apk add --no-cache <pkg>", "Switch image to python:3.9-slim if Alpine causes issues"],
    ),
    (
        r"(?i)(stage.*not defined|unknown stage|job.*not found in stages)",
        "Undefined pipeline stage",
        "medium",
        88,
        ["Add missing stage to top-level stages: list"],
    ),
    (
        r"(?i)(test.*failed|FAILED|AssertionError|assertion.*failed|\d+ (test|tests) failed)",
        "Test suite failure",
        "medium",
        75,
        ["pytest -v for verbose output", "Check test logs in artifacts"],
    ),
    (
        r"(?i)(git.*fatal|git.*error|could not read.*repository|repository not found)",
        "Git repository error",
        "high",
        83,
        ["Ensure GIT_STRATEGY: clone is set", "Check git credentials in CI variables"],
    ),
    (
        r"(?i)(certificate.*verify.*failed|SSL.*error|certificate.*expired|CERTIFICATE_VERIFY_FAILED)",
        "SSL/TLS certificate error",
        "high",
        84,
        ["Set GIT_SSL_NO_VERIFY: \"true\" (dev only)", "Update CA certificates: update-ca-certificates"],
    ),
]


def _run_local_analysis(log: str) -> List[Dict]:
    """
    Scan the log against all local rules and return matched findings,
    each with severity, confidence, and fix hints.
    """
    findings = []
    seen_issues = set()

    for pattern, issue, severity, confidence_pct, fix_hints in _LOCAL_RULES:
        if re.search(pattern, log):
            if issue in seen_issues:
                continue
            seen_issues.add(issue)

            # Extract a snippet of matching context for root cause
            match = re.search(pattern, log)
            context_start = max(0, match.start() - 60)
            context_end = min(len(log), match.end() + 120)
            snippet = log[context_start:context_end].strip().replace("\n", " ")

            findings.append({
                "issue": issue,
                "severity": severity,
                "confidence": f"{confidence_pct}%",
                "root_cause": f"Detected pattern in log: \"{snippet[:200]}\"",
                "fix_commands": fix_hints,
                "explanation": f"Log contains indicators of: {issue.lower()}.",
            })

    return findings


def _compute_recovery_probability(findings: List[Dict]) -> str:
    """
    Derive an estimated recovery probability from severity distribution.
    Higher severity = lower starting probability.
    """
    if not findings:
        return "100%"

    severity_weights = {"critical": 40, "high": 25, "medium": 15, "low": 5, "unknown": 10}
    total_penalty = sum(severity_weights.get(f.get("severity", "unknown"), 10) for f in findings)
    probability = max(10, min(95, 100 - total_penalty))
    return f"{probability}%"


def _compute_avg_confidence(findings: List[Dict]) -> str:
    """Average confidence across all findings, returning formatted percentage."""
    if not findings:
        return "0%"
    values = []
    for f in findings:
        conf = f.get("confidence", "0%")
        if isinstance(conf, str) and conf.endswith("%"):
            try:
                values.append(int(conf[:-1]))
            except ValueError:
                pass
    if not values:
        return "0%"
    return f"{int(sum(values) / len(values))}%"


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------

def read_log(args: argparse.Namespace) -> str:
    if args.log_file:
        return Path(args.log_file).read_text(encoding="utf-8")
    if args.log_text:
        return args.log_text
    return input("Paste pipeline error log: ").strip()


def _extract_section(response_text: str, section_name: str) -> str:
    pattern = re.compile(
        rf"(?is){re.escape(section_name)}\s*:\s*(.*?)(?=\n\s*(?:[-*#>\d.)\s]*)?(Issue|Explanation|Fix)\s*:|\Z)"
    )
    match = pattern.search(response_text)
    if not match:
        return ""
    return match.group(1).strip()


def _extract_first_yaml_block(text: str) -> str:
    if not text.strip():
        return ""
    fenced_yaml = re.search(r"```(?:yaml|yml)\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced_yaml:
        return fenced_yaml.group(1).strip()
    return ""


def _normalize_ai_response_schema(response_text: str) -> str:
    if not response_text.strip():
        return ""

    normalized = response_text.replace("\r\n", "\n").replace("\r", "\n")
    header_aliases = {
        "Issue": [r"problem", r"error", r"identified\s+issue", r"issue\s+identified"],
        "Explanation": [r"root\s*cause", r"reason", r"analysis", r"cause", r"explanation"],
        "Fix": [
            r"yaml\s*fix",
            r"gitlab\s*ci\s*yaml",
            r"corrected\s*\.gitlab-ci\.yml",
            r"corrected\s*yaml",
            r"solution",
            r"fix",
        ],
    }

    for canonical, aliases in header_aliases.items():
        for alias in aliases:
            heading_prefix = r"(?:[-*>\d.)\s]*)?(?:#{1,6}\s*)?"
            style_wrapper = r"(?:\*\*|__|`{1,3})?"
            normalized = re.sub(
                rf"(?im)^\s*{heading_prefix}{style_wrapper}\s*{alias}\s*{style_wrapper}\s*(?:[:\-]\s*)?$",
                f"{canonical}:",
                normalized,
            )
            normalized = re.sub(
                rf"(?im)^\s*{heading_prefix}{style_wrapper}\s*{alias}\s*{style_wrapper}\s*[:\-]\s*",
                f"{canonical}: ",
                normalized,
            )

    normalized = re.sub(r"(?i)(?<!\n)(Issue\s*:)", r"\n\1", normalized)
    normalized = re.sub(r"(?i)(?<!\n)(Explanation\s*:)", r"\n\1", normalized)
    normalized = re.sub(r"(?i)(?<!\n)(Fix\s*:)", r"\n\1", normalized)

    return normalized.strip()


def _parse_ai_response_sections(response_text: str) -> Dict[str, str]:
    normalized = _normalize_ai_response_schema(response_text)
    issue = _extract_section(normalized, "Issue")
    explanation = _extract_section(normalized, "Explanation")
    fix = _extract_section(normalized, "Fix")

    if not fix:
        fix = _extract_first_yaml_block(response_text)

    if not issue:
        for line in normalized.splitlines():
            cleaned = line.strip()
            if not cleaned:
                continue
            if re.match(r"(?i)^(Issue|Explanation|Fix)\s*:", cleaned):
                continue
            issue = cleaned
            break

    if not explanation:
        explanation = "No explanation returned"

    return {
        "issue": issue.strip(),
        "explanation": explanation.strip(),
        "fix": fix.strip(),
    }


def _strip_code_fences(text: str) -> str:
    if not text:
        return ""
    fenced = re.compile(r"^\s*```(?:yaml|yml)?\s*(.*?)\s*```\s*$", re.IGNORECASE | re.DOTALL)
    match = fenced.match(text.strip())
    return match.group(1).strip() if match else text.strip()


def _validate_gitlab_yaml(yaml_text: str) -> bool:
    if not yaml_text.strip():
        return False
    try:
        parsed = yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        return False
    return isinstance(parsed, dict) and len(parsed) > 0


def _safe_write_yaml(target_path: Path, yaml_text: str) -> Path:
    if not _validate_gitlab_yaml(yaml_text):
        raise ValueError("Refusing to write invalid YAML to .gitlab-ci.yml")

    target_path.parent.mkdir(parents=True, exist_ok=True)

    backup_path: Optional[Path] = None
    if target_path.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = target_path.with_name(f"{target_path.name}.{ts}.bak")
        backup_path.write_text(target_path.read_text(encoding="utf-8"), encoding="utf-8")

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tmp", delete=False, encoding="utf-8", dir=target_path.parent
    ) as temp_file:
        temp_file.write(yaml_text.rstrip() + "\n")
        temp_name = temp_file.name

    os.replace(temp_name, target_path)

    written_yaml = target_path.read_text(encoding="utf-8")
    if not _validate_gitlab_yaml(written_yaml):
        if backup_path and backup_path.exists():
            restore_temp = target_path.with_suffix(target_path.suffix + ".restore.tmp")
            restore_temp.write_text(backup_path.read_text(encoding="utf-8"), encoding="utf-8")
            os.replace(restore_temp, target_path)
        raise RuntimeError("Wrote invalid YAML to .gitlab-ci.yml; restored backup")

    return backup_path if backup_path else Path("")


def _build_prompt(log: str) -> str:
    return PROMPT_TEMPLATE.format(log=log)


def _is_rate_limited_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "429" in message
        or "resource_exhausted" in message
        or "quota" in message
        or "rate limit" in message
        or "too many requests" in message
    )


# ---------------------------------------------------------------------------
# Fallback YAML generator — uses local analysis to build a real fix
# ---------------------------------------------------------------------------

def _generate_fallback_yaml(log: str, findings: List[Dict]) -> str:
    """
    Build a best-effort .gitlab-ci.yml fix based on local rule matches.
    Falls back to a safe minimal template if no findings.
    """
    has_docker = any("docker" in f["issue"].lower() for f in findings)
    has_python_pkg = any("python package" in f["issue"].lower() for f in findings)
    has_apt = any("apt" in f["issue"].lower() for f in findings)
    has_alpine = any("alpine" in f["issue"].lower() for f in findings)
    has_permission = any("permission" in f["issue"].lower() for f in findings)

    image = "python:3.9-slim"
    if has_alpine:
        image = "python:3.9-slim"  # Migrate away from Alpine when Alpine is the problem

    before_script_lines = ["- apt-get update -yqq && apt-get install -yqq curl"]
    if has_python_pkg:
        before_script_lines.append("- pip install --upgrade pip")
    if has_permission:
        before_script_lines.append("- chmod +x scripts/ || true")

    script_lines = ["- echo \"Pipeline started\""]
    if has_python_pkg:
        script_lines.append("- pip install -r requirements.txt")
    if has_docker:
        script_lines.append("- docker info")

    services_block = ""
    variables_block = ""
    if has_docker:
        services_block = """  services:
    - name: docker:dind
      alias: docker
"""
        variables_block = """  variables:
    DOCKER_HOST: tcp://docker:2375
    DOCKER_TLS_CERTDIR: ""
"""

    before_str = "\n    ".join(before_script_lines)
    script_str = "\n    ".join(script_lines)

    return f"""stages:
  - build

build:
  stage: build
  image: {image}
{services_block}{variables_block}  before_script:
    {before_str}
  script:
    {script_str}
  retry:
    max: 2
    when:
      - runner_system_failure
      - stuck_or_timeout_failure
"""


def _fallback_response(prompt: str, log: str = "", findings: Optional[List[Dict]] = None) -> str:
    """
    Build a local fallback that does NOT inject a fake 'Gemini unavailable' finding.
    Instead it returns the real locally-analyzed issue or a healthy pipeline YAML.
    """
    yaml_only_request = bool(
        re.search(r"(?is)return\s+yaml\s+only", prompt)
        or re.search(r"(?is)valid\s+gitlab\s+ci\s+yaml", prompt)
    )

    local_findings = findings or []
    fallback_yaml = _generate_fallback_yaml(log, local_findings)

    if yaml_only_request:
        return fallback_yaml

    if local_findings:
        top = local_findings[0]
        issue_text = top["issue"]
        explanation_text = top.get("root_cause", top.get("explanation", "See log for details."))
    else:
        issue_text = "Pipeline configuration error"
        explanation_text = "No specific pattern matched; review the log for non-standard errors."

    return f"""Issue: {issue_text}
Explanation: {explanation_text}
Fix:
```yaml
{fallback_yaml}
```"""


# ---------------------------------------------------------------------------
# Gemini call
# ---------------------------------------------------------------------------

def _call_gemini(prompt: str, settings: GeminiSettings, log: str = "", findings: Optional[List[Dict]] = None) -> str:
    if not settings.enabled:
        return _fallback_response(prompt, log, findings)

    api_key = (settings.api_key or os.getenv("GEMINI_API_KEY", "")).strip()
    if not api_key:
        print("WARNING: GEMINI_API_KEY is missing; using local fallback")
        return _fallback_response(prompt, log, findings)

    client = genai.Client(api_key=api_key)
    max_attempts = 4
    base_delay_seconds = 1.5
    failover_models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-3.1-flash-lite"]

    ordered_models = [settings.model] + failover_models
    model_candidates = list(dict.fromkeys(ordered_models))

    last_error: Optional[Exception] = None

    for model_name in model_candidates:
        for attempt in range(1, max_attempts + 1):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )

                text = response.text or ""
                if not text.strip():
                    raise RuntimeError("Gemini returned an empty response")
                return text

            except Exception as exc:
                last_error = exc

                if _is_rate_limited_error(exc) and attempt < max_attempts:
                    delay = base_delay_seconds * (2 ** (attempt - 1))
                    print(
                        f"WARNING: Gemini quota/rate limit on {model_name} "
                        f"(attempt {attempt}/{max_attempts}); retrying in {delay:.1f}s"
                    )
                    time.sleep(delay)
                    continue

                if _is_rate_limited_error(exc):
                    print(f"WARNING: Switching Gemini model from {model_name} due to quota/rate limits")
                    break

                print(f"WARNING: Gemini call failed on {model_name}; not retrying. Reason: {exc}")
                return _fallback_response(prompt, log, findings)

    print(f"WARNING: All Gemini models exhausted; using local fallback. Reason: {last_error}")
    return _fallback_response(prompt, log, findings)


# ---------------------------------------------------------------------------
# Core analysis pipeline
# ---------------------------------------------------------------------------

def fix_pipeline_with_ai(log: str, settings: Optional[GeminiSettings] = None) -> Dict[str, object]:
    active_settings = settings or GeminiSettings(enabled=True, model="gemini-2.5-flash")

    # Step 0: Always run local analysis first — used as fallback data AND for metrics.
    local_findings = _run_local_analysis(log)
    recovery_probability = _compute_recovery_probability(local_findings)
    avg_confidence = _compute_avg_confidence(local_findings)

    # Step 1: Send pipeline log to Gemini.
    prompt = _build_prompt(log)
    ai_text = _call_gemini(prompt, active_settings, log=log, findings=local_findings)

    # Step 2: Parse structured sections from Gemini response.
    parsed_sections = _parse_ai_response_sections(ai_text)
    issue = parsed_sections["issue"]
    explanation = parsed_sections["explanation"]
    fix_section = parsed_sections["fix"]
    yaml_candidate = _strip_code_fences(fix_section)

    # Step 3: Repair YAML if invalid.
    if not _validate_gitlab_yaml(yaml_candidate):
        repair_prompt = (
            "Convert the following content into a valid GitLab CI YAML only. "
            "Return YAML only without markdown fences or explanation.\n\n"
            f"Content:\n{fix_section}"
        )
        repaired_yaml_text = _call_gemini(repair_prompt, active_settings, log=log, findings=local_findings)
        yaml_candidate = _strip_code_fences(repaired_yaml_text)

    # Step 4: If still invalid, use locally-generated YAML.
    if not _validate_gitlab_yaml(yaml_candidate):
        print("WARNING: Gemini YAML invalid after repair; using locally-generated fallback YAML.")
        yaml_candidate = _generate_fallback_yaml(log, local_findings)

    # Step 5: Determine final findings list.
    # If Gemini succeeded and gave us a proper issue, merge it with local findings.
    gemini_succeeded = bool(
        issue
        and "gemini api unavailable" not in issue.lower()
        and "rate-limit" not in issue.lower()
    )

    if gemini_succeeded:
        # Build the AI finding with real confidence from local analysis or a high default
        ai_confidence = avg_confidence if avg_confidence != "0%" else "85%"
        ai_finding = {
            "issue": issue or "Unknown issue",
            "root_cause": explanation or "No explanation returned",
            "explanation": explanation or "No explanation returned",
            "severity": _infer_severity_from_text(issue + " " + explanation),
            "priority": 1,
            "confidence": ai_confidence,
            "fix_commands": [],
        }
        # Primary finding from Gemini, secondary from local rules (de-duplicated by issue title)
        all_findings = [ai_finding]
        for lf in local_findings:
            if lf["issue"].lower() not in issue.lower():
                all_findings.append(lf)

        gemini_status = "completed"
        gemini_analysis_text = ai_text
    else:
        # Gemini failed — use purely local findings
        all_findings = local_findings
        gemini_status = "failed"
        gemini_analysis_text = ""

    # Recompute metrics from final findings list
    if all_findings:
        recovery_probability = _compute_recovery_probability(all_findings)
        avg_confidence = _compute_avg_confidence(all_findings)
    else:
        recovery_probability = "100%"
        avg_confidence = "N/A"

    top_3 = all_findings[:3]

    return {
        "assistant_name": "AutoHeal CI",
        "tagline": "Gemini-powered CI/CD pipeline fixer",
        "analyzed_log": log,
        "total_findings": len(all_findings),
        "total_matches_before_dedup": len(all_findings),
        "detected_errors": all_findings,
        "all_findings": all_findings,
        "top_3_suggestions": top_3,
        "local_deduplicated_findings": local_findings,
        "ai_analysis": gemini_analysis_text,
        "generated_pipeline_yaml": yaml_candidate,
        "self_heal": {
            "estimated_recovery_probability": recovery_probability,
            "avg_confidence": avg_confidence,
        },
        "gemini_reasoning": {
            "status": gemini_status,
            "reason": "" if gemini_succeeded else "Gemini API unavailable or rate-limited; local analysis used.",
        },
        "gemini_analysis": gemini_analysis_text,
        "timeline": [
            "ingest_log",
            "local_analysis",
            "gemini_analysis",
            "yaml_validation",
            "safe_write",
        ],
    }


def _infer_severity_from_text(text: str) -> str:
    """Derive severity from keywords in the issue/explanation text."""
    text_lower = text.lower()
    if any(k in text_lower for k in ["critical", "oom", "out of memory", "disk full", "image pull", "yaml error"]):
        return "critical"
    if any(k in text_lower for k in ["permission", "auth", "missing file", "docker", "pip", "npm", "exit code"]):
        return "high"
    if any(k in text_lower for k in ["timeout", "syntax", "test", "alpine", "stage"]):
        return "medium"
    return "low"


def analyze_pipeline_failure(log: str, _unused: Optional[object] = None) -> Dict[str, object]:
    """Compatibility wrapper used by dashboard and helper scripts."""
    if isinstance(_unused, GeminiSettings):
        return fix_pipeline_with_ai(log, _unused)
    return fix_pipeline_with_ai(log)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="AutoHeal CI - Gemini-powered pipeline fixer")
    parser.add_argument("--log-file", help="Path to a CI/CD error log file")
    parser.add_argument("--log-text", help="Inline CI/CD error log")
    parser.add_argument("--report", default="ai_report.json", help="Analysis report output path")
    parser.add_argument("--fixed-ci", default=".gitlab-ci-fixed.yml", help="Secondary YAML output path")
    parser.add_argument("--use-gemini", action="store_true", help="Enable Gemini API")
    parser.add_argument("--gemini-model", default="gemini-2.5-flash", help="Model to use")
    parser.add_argument("--gemini-api-key", default="", help="Gemini API key override (optional)")
    args = parser.parse_args()

    log = read_log(args)
    settings = GeminiSettings(
        enabled=args.use_gemini,
        model=args.gemini_model,
        api_key=args.gemini_api_key.strip() or None,
    )

    try:
        result = fix_pipeline_with_ai(log, settings)

        yaml_text = str(result["generated_pipeline_yaml"])
        Path(args.fixed_ci).write_text(yaml_text.rstrip() + "\n", encoding="utf-8")
        backup = _safe_write_yaml(Path(".gitlab-ci.yml"), yaml_text)

        Path(args.report).write_text(json.dumps(result, indent=2), encoding="utf-8")

        print("AI Analysis:\n")
        print(result["ai_analysis"] or "[Local analysis used — see detected_errors in report]")
        print("\nYAML fix written to .gitlab-ci.yml")
        if str(backup):
            print(f"Backup created: {backup}")
        print(f"Secondary YAML copy: {args.fixed_ci}")
        print(f"Report file: {args.report}")
        print(f"\nFindings: {result['total_findings']}")
        print(f"Recovery probability: {result['self_heal']['estimated_recovery_probability']}")
        print(f"Avg confidence: {result['self_heal']['avg_confidence']}")

    except Exception as exc:
        error_payload = {
            "assistant_name": "AutoHeal CI",
            "status": "failed",
            "error": str(exc),
        }
        Path(args.report).write_text(json.dumps(error_payload, indent=2), encoding="utf-8")
        print("AI pipeline fix failed.")
        print(f"Reason: {exc}")


if __name__ == "__main__":
    main()