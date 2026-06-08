#!/usr/bin/env python3
"""
SKVA Core Engine — spawn, monitor, verify agents.
Usage: python3 skva-core.py solo "create hello world"
       python3 skva-core.py council "design a calculator"
"""
import json, os, sys, time, subprocess, shlex, signal
from pathlib import Path

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))

def log(msg, level="INFO"):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)

def escape_prompt(text):
    """Escape text for shell-in-shell (ssh → hermes)."""
    return shlex.quote(text)

def agent_heartbeat(role, project_dir):
    """Write heartbeat file."""
    hb_file = Path(project_dir) / ".hermes" / "signals" / "heartbeat" / f"{role}.live"
    hb_file.parent.mkdir(parents=True, exist_ok=True)
    with open(hb_file, "w") as f:
        json.dump({"ts": time.time(), "role": role}, f)

def check_heartbeat(role, project_dir, timeout=180):
    """Check if agent is alive. Returns True if heartbeat within timeout."""
    hb_file = Path(project_dir) / ".hermes" / "signals" / "heartbeat" / f"{role}.live"
    if not hb_file.exists():
        return False
    try:
        data = json.loads(hb_file.read_text())
        age = time.time() - data["ts"]
        return age < timeout
    except:
        return False

def signal_done(phase, project_dir):
    """Signal phase completion."""
    sig_file = Path(project_dir) / ".hermes" / "signals" / f".{phase}.done"
    sig_file.parent.mkdir(parents=True, exist_ok=True)
    sig_file.touch()

def signal_fail(phase, reason, project_dir):
    """Signal phase failure with reason."""
    sig_file = Path(project_dir) / ".hermes" / "signals" / f".{phase}.fail"
    sig_file.parent.mkdir(parents=True, exist_ok=True)
    sig_file.write_text(json.dumps({
        "reason": reason,
        "timestamp": time.time(),
        "phase": phase
    }))

def check_gate(phase, project_dir, timeout=600, interval=15):
    """Wait for a gate signal. Returns True if passed, False if failed/timeout."""
    done_file = Path(project_dir) / ".hermes" / "signals" / f".{phase}.done"
    fail_file = Path(project_dir) / ".hermes" / "signals" / f".{phase}.fail"
    waited = 0
    while waited < timeout:
        if fail_file.exists():
            reason = fail_file.read_text().strip()
            log(f"Gate {phase} FAILED: {reason}", "ERROR")
            return False
        if done_file.exists():
            log(f"Gate {phase} PASSED ({waited}s)", "OK")
            return True
        time.sleep(interval)
        waited += interval
        if waited % 60 == 0:
            log(f"Waiting for {phase}... ({waited}s)")
    log(f"Gate {phase} TIMEOUT ({timeout}s)", "ERROR")
    return False

def spawn_agent(role, prompt_template, project_dir, model="deepseek-flash", timeout=900):
    """Spawn a Hermes agent in the background. Returns True if successful."""
    project_dir = os.path.abspath(project_dir)
    artifacts_dir = Path(project_dir) / ".hermes" / "artifacts" / role
    signals_dir = Path(project_dir) / ".hermes" / "signals"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    signals_dir.mkdir(parents=True, exist_ok=True)

    # Build the prompt for the agent
    prompt = f"""
Твоя роль: {role}
Проект: {project_dir}

Задача: {prompt_template}

Інструкції:
1. Працюй в {artifacts_dir}/
2. Пиши heartbeat кожні 60с:
   echo '{{"ts":{int(time.time())}}}' > {signals_dir}/heartbeat/{role}.live
3. Коли готово — touch {signals_dir}/.{role}.done
4. Якщо помилка — echo "причина" > {signals_dir}/.{role}.fail
5. НЕ чіпай файли інших агентів
"""

    safe_prompt = escape_prompt(prompt)
    cmd = f"hermes chat -q {safe_prompt}"

    log(f"Spawning {role} (model={model}, timeout={timeout}s)")
    
    try:
        result = subprocess.run(
            ["hermes", "chat", "-q", prompt],
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "HERMES_HOME": HERMES_HOME}
        )
        if result.returncode == 0:
            log(f"{role} completed successfully")
            signal_done(role, project_dir)
            return True
        else:
            err = result.stderr[:200] if result.stderr else "unknown error"
            log(f"{role} failed: {err}", "ERROR")
            signal_fail(role, err, project_dir)
            return False
    except subprocess.TimeoutExpired:
        log(f"{role} TIMEOUT after {timeout}s", "ERROR")
        signal_fail(role, f"timeout after {timeout}s", project_dir)
        return False
    except Exception as e:
        log(f"{role} exception: {e}", "ERROR")
        signal_fail(role, str(e), project_dir)
        return False

def spawn_agent_background(role, prompt_template, project_dir, model="deepseek-flash"):
    """Spawn agent in background. Returns process."""
    prompt = f"Твоя роль: {role}. Проект: {project_dir}. {prompt_template}"
    log(f"Background spawn: {role}")
    proc = subprocess.Popen(
        ["hermes", "chat", "-q", prompt],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={**os.environ, "HERMES_HOME": HERMES_HOME}
    )
    return proc

def verify_phase(phase, project_dir):
    """Verify phase artifacts."""
    project = Path(project_dir)
    
    if phase == "solo":
        # Just check that something was created in artifacts
        arts = list((project / ".hermes" / "artifacts").rglob("*"))
        if arts:
            log(f"Solo artifacts: {len(arts)} files", "OK")
            return True
        log("No artifacts found", "ERROR")
        return False
    
    if phase == "council":
        # Check spec and arch exist
        council = project / ".hermes" / "artifacts" / "council"
        spec = council / "spec.md"
        arch = council / "arch.md"
        if spec.exists() and arch.exists():
            log(f"Council OK: spec ({spec.stat().st_size}b) + arch ({arch.stat().st_size}b)", "OK")
            return True
        log("Council artifacts incomplete", "ERROR")
        return False
    
    if phase == "factory":
        # Check code compiles
        src = project / "src"
        if not src.exists() or not any(src.iterdir()):
            log("No source code found", "ERROR")
            return False
        # Try npm test if package.json exists
        pkg = project / "package.json"
        if pkg.exists():
            r = subprocess.run(["npm", "test"], cwd=str(project), capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                log(f"npm test failed: {r.stderr[:200]}", "WARN")
                return False
            log("npm test passed", "OK")
        return True
    
    if phase == "deploy":
        url_file = project / ".hermes" / "artifacts" / "deploy" / "url.txt"
        if url_file.exists():
            log(f"Deploy URL: {url_file.read_text().strip()}", "OK")
            return True
        log("No deploy URL found", "ERROR")
        return False
    
    return True  # default: pass

def solo(request, project_dir="."):
    """Execute Solo method: one agent does everything."""
    project_dir = os.path.abspath(project_dir)
    Path(project_dir).mkdir(parents=True, exist_ok=True)
    (Path(project_dir) / ".hermes" / "signals").mkdir(parents=True, exist_ok=True)
    
    log(f"=== SOLO: {request} ===")
    start = time.time()
    
    # Spawn single agent
    ok = spawn_agent("fullstack", request, project_dir, timeout=900)
    if not ok:
        log("SOLO FAILED", "ERROR")
        return False
    
    # Verify
    verified = verify_phase("solo", project_dir)
    elapsed = time.time() - start
    
    log(f"=== SOLO DONE ({elapsed:.0f}s) ===")
    return verified

def main():
    if len(sys.argv) < 3:
        print("Usage: skva-core.py <method> <request> [project-dir]")
        print("Methods: solo, council, factory, deploy, verify")
        sys.exit(1)
    
    method = sys.argv[1]
    request = sys.argv[2]
    project_dir = sys.argv[3] if len(sys.argv) > 3 else "."
    
    if method == "solo":
        ok = solo(request, project_dir)
        sys.exit(0 if ok else 1)
    elif method == "council":
        council_dir = Path(project_dir) / ".hermes" / "artifacts" / "council"
        council_dir.mkdir(parents=True, exist_ok=True)
        spawn_agent("architect", f"Write architecture spec for: {request}", project_dir)
        spawn_agent("analyst", f"Write requirements spec for: {request}", project_dir)
    elif method == "factory":
        spawn_agent("developer", f"Implement: {request}", project_dir, model="qwen3-235b")
    elif method == "verify":
        ok = verify_phase("solo", project_dir)
        sys.exit(0 if ok else 1)
    else:
        print(f"Unknown method: {method}")
        sys.exit(1)

if __name__ == "__main__":
    main()
