"""Exporta resultados Surefire e disponibilidade HTTP sem propriedades de ambiente."""
import argparse
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import subprocess
from urllib.request import urlopen
import xml.etree.ElementTree as ET

parser = argparse.ArgumentParser()
parser.add_argument("java_repo", type=Path)
parser.add_argument("--output", type=Path, default=Path("evidencias"))
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
now = datetime.now(timezone.utc).isoformat()
suites = []
for path in sorted((args.java_repo / "target/surefire-reports").glob("TEST-*.xml")):
    root = ET.parse(path).getroot()
    cases = []
    for case in root.findall("testcase"):
        cases.append({"name": case.get("name"), "class": case.get("classname"),
                      "status": "skipped" if case.find("skipped") is not None else
                      "failed" if case.find("failure") is not None or case.find("error") is not None else "passed"})
    suites.append({"name": root.get("name"), "tests": int(root.get("tests", 0)),
                   "failures": int(root.get("failures", 0)), "errors": int(root.get("errors", 0)),
                   "skipped": int(root.get("skipped", 0)), "seconds": float(root.get("time", 0)),
                   "cases": cases})
if not suites:
    raise SystemExit("Execute mvn -B verify antes de coletar os relatórios")
commit = subprocess.check_output(["git", "-C", str(args.java_repo), "rev-parse", "HEAD"], text=True).strip()
report = {"collectedAt": now, "javaCommit": commit, "suiteCount": len(suites),
          "totals": {k: sum(s[k] for s in suites) for k in ("tests", "failures", "errors", "skipped")},
          "suites": suites, "scope": "Testes locais Java com banco/broker descartáveis e clientes IA controlados"}
build_log = args.java_repo / "evidence-verify-local.log"
if build_log.exists():
    raw = build_log.read_bytes()
    report["build"] = {"command": "mvn -B verify", "success": b"BUILD SUCCESS" in raw,
                       "logSha256": hashlib.sha256(raw).hexdigest(),
                       "javaVersion": "Temurin 21.0.9", "mavenVersion": "3.9.16"}
(args.output / "testes-java.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
checks = []
for path in ("/actuator/health", "/v3/api-docs", "/swagger-ui/index.html"):
    try:
        with urlopen("https://agroconecta-api-ms1a.onrender.com" + path, timeout=60) as response:
            body = response.read()
            check = {"path": path, "httpStatus": response.status}
            if path.endswith("health"):
                check["applicationStatus"] = json.loads(body).get("status")
            if path.endswith("api-docs"):
                schema = json.loads(body)
                check["guidanceRoutePresent"] = "/api/risk-jobs/{id}/guidance" in schema.get("paths", {})
                check["jwtDocumented"] = any(s.get("scheme") == "bearer" for s in
                    schema.get("components", {}).get("securitySchemes", {}).values())
            checks.append(check)
    except Exception:
        checks.append({"path": path, "error": "Verificação HTTP indisponível"})
(args.output / "disponibilidade-api.json").write_text(json.dumps({"collectedAt": now, "checks": checks},
    indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(report["totals"]))
