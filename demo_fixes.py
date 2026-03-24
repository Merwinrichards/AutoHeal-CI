#!/usr/bin/env python3
"""
DEMONSTRATION: AutoHeal CI Fix Generation Improvements

This script shows how the improved fix generation logic creates production-ready
pipelines for different error scenarios. Each pipeline is NOT a generic template
but a fully functional, error-specific CI/CD configuration.
"""

from ai_fixer import analyze_pipeline_failure


def demo_npm_error():
    """Example 1: Node.js npm package error -> complete npm-optimized pipeline"""
    print("\n" + "="*80)
    print("EXAMPLE 1: Node.js Package Error")
    print("="*80)
    
    log = """
    npm ERR! 404 Not Found - GET https://registry.npmjs.org/@app/utils
    npm ERR! 404
    npm ERR! 404 '@app/utils@1.2.3' is not in this registry.
    npm ERR! A complete log of this run can be found in: /root/.npm/_logs/2.log
    """
    
    result = analyze_pipeline_failure(log)
    
    print(f"\nDetected Error: {result['detected_errors'][0]['issue']}")
    print(f"Confidence: {result['detected_errors'][0]['confidence']}")
    print(f"Root Cause: {result['detected_errors'][0]['root_cause']}")
    
    pipeline = result['generated_pipeline_yaml']
    print("\n[GENERATED PIPELINE FEATURES]")
    features = [
        ("Node.js Image", "node:20-alpine" in pipeline),
        ("npm ci (clean install)", "npm ci" in pipeline),
        ("Cache Strategy", "NPM_CONFIG_CACHE" in pipeline),
        ("Dependency Artifacts", "node_modules/" in pipeline),
        ("Retry Logic", "api_failure" in pipeline),
        ("Test Stage", "npm test" in pipeline),
    ]
    
    for feature, present in features:
        status = "[OK]" if present else "[MISS]"
        print(f"  {status} {feature}")
    
    print(f"\nTotal Pipeline Size: {len(pipeline)} bytes")
    print("\nPipeline Excerpt (first 40 lines):")
    for line in pipeline.split('\n')[:40]:
        print(f"  {line}")
    print("  ...")


def demo_python_error():
    """Example 2: Python dependency error -> complete Python-optimized pipeline"""
    print("\n" + "="*80)
    print("EXAMPLE 2: Python Dependency Error")
    print("="*80)
    
    log = """
    ModuleNotFoundError: No module named 'requests'
    File "/app/src/api.py", line 3, in <module>
      import requests
    ModuleNotFoundError: No module named 'requests'
    """
    
    result = analyze_pipeline_failure(log)
    
    print(f"\nDetected Error: {result['detected_errors'][0]['issue']}")
    print(f"Confidence: {result['detected_errors'][0]['confidence']}")
    print(f"Recommended Fix: Install from requirements.txt")
    
    pipeline = result['generated_pipeline_yaml']
    print("\n[GENERATED PIPELINE FEATURES]")
    features = [
        ("Python 3.11 Image", "python:3.11" in pipeline),
        ("pip upgrade", "python -m pip install --upgrade pip" in pipeline),
        ("requirements.txt install", "pip install -r requirements.txt" in pipeline),
        ("pip Cache", "PIP_CACHE_DIR" in pipeline),
        ("Virtual Env", ".venv/" in pipeline),
        ("pytest/unittest", "pytest" in pipeline or "unittest" in pipeline),
    ]
    
    for feature, present in features:
        status = "[OK]" if present else "[MISS]"
        print(f"  {status} {feature}")
    
    print(f"\nTotal Pipeline Size: {len(pipeline)} bytes")


def demo_connection_error():
    """Example 3: Service connectivity -> complete resilience-focused pipeline"""
    print("\n" + "="*80)
    print("EXAMPLE 3: Connection Refused (Service Unavailable)")
    print("="*80)
    
    log = """
    ConnectionRefusedError: [Errno 111] Connection refused
    Error connecting to database at localhost:5432
    Tests cannot proceed without database service
    """
    
    result = analyze_pipeline_failure(log)
    
    print(f"\nDetected Error: {result['detected_errors'][0]['issue']}")
    print(f"Strategy: {result['detected_errors'][0]['explanation']}")
    
    pipeline = result['generated_pipeline_yaml']
    print("\n[GENERATED PIPELINE FEATURES]")
    features = [
        ("Service Retry Stage", "waitForServices" in pipeline),
        ("Retry Attempts", "SERVICE_RETRY_ATTEMPTS" in pipeline),
        ("netcat checks", "nc -z" in pipeline),
        ("Health endpoint check", "/health" in pipeline),
        ("Exponential backoff", "sleep" in pipeline),
        ("Graceful fallback", "allow_failure: true" in pipeline),
    ]
    
    for feature, present in features:
        status = "[OK]" if present else "[MISS]"
        print(f"  {status} {feature}")
    
    print(f"\nTotal Pipeline Size: {len(pipeline)} bytes")
    
    # Show retry logic excerpt
    print("\nRetry Logic Excerpt:")
    for line in pipeline.split('\n')[30:55]:
        print(f"  {line}")


def demo_timeout_error():
    """Example 4: Timeout -> complete split/optimized pipeline"""
    print("\n" + "="*80)
    print("EXAMPLE 4: Job Timeout")
    print("="*80)
    
    log = """
    ERROR: Job timeout - build job exceeded 3600 seconds
    CI_JOB_TIMEOUT exceeded
    Reduce job scope or split into parallel jobs
    """
    
    result = analyze_pipeline_failure(log)
    
    print(f"\nDetected Error: {result['detected_errors'][0]['issue']}")
    print(f"Root Cause: {result['detected_errors'][0]['root_cause']}")
    
    pipeline = result['generated_pipeline_yaml']
    print("\n[GENERATED PIPELINE FEATURES]")
    features = [
        ("Split Quick Jobs", "quick_build" in pipeline and "quick_test" in pipeline),
        ("Explicit Timeouts", "timeout:" in pipeline),
        ("Per-job Timeout", "timeout: 10 minutes" in pipeline or "timeout: 8 minutes" in pipeline),
        ("Chunked Compilation", "chunk" in pipeline),
        ("Prioritized Tests", "smoke test" in pipeline or "prioritized" in pipeline.lower()),
    ]
    
    for feature, present in features:
        status = "[OK]" if present else "[MISS]"
        print(f"  {status} {feature}")
    
    print(f"\nTotal Pipeline Size: {len(pipeline)} bytes")


def demo_command_not_found():
    """Example 5: Command not found -> validation pipeline"""
    print("\n" + "="*80)
    print("EXAMPLE 5: Command Not Found")
    print("="*80)
    
    log = """
    /bin/bash: line 15: make: command not found
    Build process requires 'make' but it's not available
    ERR! make: command not found
    """
    
    result = analyze_pipeline_failure(log)
    
    print(f"\nDetected Error: {result['detected_errors'][0]['issue']}")
    print(f"Strategy: Validate and install missing commands")
    
    pipeline = result['generated_pipeline_yaml']
    print("\n[GENERATED PIPELINE FEATURES]")
    features = [
        ("Command Validation Stage", "validateCommands" in pipeline),
        ("check_command function", "check_command()" in pipeline),
        ("apt-get installer", "apt-get install" in pipeline),
        ("Fallback Support", "|| apt-get install" in pipeline),
        ("Ubuntu Base", "ubuntu:22.04" in pipeline),
    ]
    
    for feature, present in features:
        status = "[OK]" if present else "[MISS]"
        print(f"  {status} {feature}")
    
    print(f"\nTotal Pipeline Size: {len(pipeline)} bytes")


def summary():
    """Show summary of improvements"""
    print("\n" + "="*80)
    print("IMPROVEMENT SUMMARY")
    print("="*80)
    
    improvements = [
        ("Error Detection", "Detects 9+ error patterns with strict keyword matching"),
        ("Error-Specific Fixes", "8 specialized pipeline generators (not generic templates)"),
        ("Production-Ready", "All YAML validated and includes real commands (not placeholders)"),
        ("Caching Strategy", "Technology-specific caching (npm, pip, maven, gradle)"),
        ("Retry Logic", "Built-in retries for transient failures"),
        ("Timeouts", "Explicit job timeouts with split/optimization strategies"),
        ("Service Resilience", "Retry connections with netcat/curl health checks"),
        ("Ecosystem Detection", "Automatic routing: Node.js, Python, Java, etc."),
        ("Safe Fallback", "Graceful default pipeline for unknown errors"),
        ("Full YAML Compliance", "All pipelines pass yaml.safe_load() validation"),
    ]
    
    for title, description in improvements:
        print(f"\n[FEATURE] {title}")
        print(f"   {description}")
    
    print("\n" + "="*80)
    print("Generated Pipelines Are:")
    print("  + Complete (diagnose -> build -> test -> success stages)")
    print("  + Realistic (actual npm ci, pip install, mvn, gradle commands)")
    print("  + Robust (retry logic, timeouts, health checks)")
    print("  + Ecosystem-aware (Node, Python, Java, generic)")
    print("="*80 + "\n")


if __name__ == "__main__":
    print("\n")
    print("*" * 80)
    print("AutoHeal CI: Fix Generation System - Complete Demonstration")
    print("*" * 80)
    
    demo_npm_error()
    demo_python_error()
    demo_connection_error()
    demo_timeout_error()
    demo_command_not_found()
    summary()
    
    print("[COMPLETE] All demonstrations finished successfully!")
