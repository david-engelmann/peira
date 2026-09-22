//! Dataset tooling: case-file loading, manifests, content hashes.
//!
//! Mirrors `python/peira/dataset.py`. A peira dataset directory holds
//! versioned case files plus a `manifest.json` that locks their exact
//! contents — the build receipt. Any case added, changed, or removed
//! produces a new dataset version with a new manifest; manifests are never
//! edited in place.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs;
use std::io::{self, Read};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::schema::{validate_case_dict, Case};

pub const MANIFEST_NAME: &str = "manifest.json";
pub const CANARY_NAME: &str = "CANARY.txt";
pub const CASE_SUFFIX: &str = ".jsonl";

/// One non-blank line of a case file: the parsed JSON or the parse error.
pub struct CaseLine {
    pub path: PathBuf,
    pub lineno: usize,
    pub result: Result<Value, String>,
}

/// Yield every non-blank line of every `*.jsonl` file in the dataset
/// directory root, in sorted filename order.
///
/// A JSON syntax error is reported per line (not raised): serde_json's
/// message differs in wording from Python's `json.JSONDecodeError`, so the
/// `invalid JSON (...)` text is close but not byte-identical across
/// languages.
pub fn iter_case_lines(dataset_dir: &Path) -> io::Result<Vec<CaseLine>> {
    let mut paths: Vec<PathBuf> = fs::read_dir(dataset_dir)?
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.is_file() && p.extension().and_then(|e| e.to_str()) == Some("jsonl"))
        .collect();
    paths.sort();
    let mut out = Vec::new();
    for path in paths {
        let text = fs::read_to_string(&path)?;
        for (lineno, line) in text.lines().enumerate() {
            if line.trim().is_empty() {
                continue;
            }
            let result = serde_json::from_str(line).map_err(|e| format!("invalid JSON ({e})"));
            out.push(CaseLine {
                path: path.clone(),
                lineno: lineno + 1,
                result,
            });
        }
    }
    Ok(out)
}

/// Load and schema-validate every case in a dataset directory.
///
/// Mirrors `runner.load_cases`: the error carries `path:lineno` context.
pub fn load_cases(dataset_dir: &Path) -> Result<Vec<Case>, String> {
    let lines =
        iter_case_lines(dataset_dir).map_err(|e| format!("cannot read dataset dir: {e}"))?;
    let mut cases = Vec::new();
    for line in lines {
        let d = line
            .result
            .map_err(|e| format!("{}:{}: {e}", line.path.display(), line.lineno))?;
        let errors = validate_case_dict(&d);
        if !errors.is_empty() {
            return Err(format!(
                "{}:{}: {}",
                line.path.display(),
                line.lineno,
                errors.join("; ")
            ));
        }
        let case = Case::from_value(&d)
            .map_err(|e| format!("{}:{}: {e}", line.path.display(), line.lineno))?;
        cases.push(case);
    }
    Ok(cases)
}

/// SHA-256 hex digest of a file's bytes.
pub fn sha256_file(path: &Path) -> io::Result<String> {
    let mut h = Sha256::new();
    let mut f = fs::File::open(path)?;
    let mut buf = [0u8; 65536];
    loop {
        let n = f.read(&mut buf)?;
        if n == 0 {
            break;
        }
        h.update(&buf[..n]);
    }
    Ok(format!("{:x}", h.finalize()))
}

/// Per-file counts for one validated case file (a manifest entry).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CaseSummary {
    pub n_cases: u64,
    pub n_by_family: BTreeMap<String, u64>,
    pub n_by_severity: BTreeMap<String, u64>,
    pub n_by_primitive: BTreeMap<String, u64>,
}

/// Validate a JSONL case file and count its cases.
///
/// Returns the manifest counts for the file. Fails listing every invalid
/// line — a dataset never builds on invalid cases. Message format mirrors
/// Python (`{name}:{lineno}: ...`, problems joined by newlines).
pub fn summarize_cases(path: &Path) -> Result<CaseSummary, String> {
    let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
    let text = fs::read_to_string(path).map_err(|e| format!("cannot read {name}: {e}"))?;
    let mut summary = CaseSummary {
        n_cases: 0,
        n_by_family: BTreeMap::new(),
        n_by_severity: BTreeMap::new(),
        n_by_primitive: BTreeMap::new(),
    };
    let mut problems = Vec::new();
    for (lineno, line) in text.lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        summary.n_cases += 1;
        let lineno = lineno + 1;
        let case: Value = match serde_json::from_str(line) {
            Ok(v) => v,
            Err(e) => {
                problems.push(format!("{name}:{lineno}: invalid JSON ({e})"));
                continue;
            }
        };
        let errors = validate_case_dict(&case);
        if !errors.is_empty() {
            problems.push(format!("{name}:{lineno}: {}", errors.join("; ")));
            continue;
        }
        for (key, map) in [
            ("family", &mut summary.n_by_family),
            ("severity", &mut summary.n_by_severity),
            ("primitive", &mut summary.n_by_primitive),
        ] {
            if let Some(s) = case.get(key).and_then(|v| v.as_str()) {
                *map.entry(s.to_string()).or_insert(0) += 1;
            }
        }
    }
    if !problems.is_empty() {
        return Err(problems.join("\n"));
    }
    Ok(summary)
}

/// One entry in a manifest's `files` section.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ManifestEntry {
    pub kind: String,
    pub sha256: String,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub n_cases: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub n_by_family: Option<BTreeMap<String, u64>>,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub n_by_severity: Option<BTreeMap<String, u64>>,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub n_by_primitive: Option<BTreeMap<String, u64>>,
}

/// A dataset build receipt. Manifests are never edited in place.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Manifest {
    pub dataset: String,
    pub dataset_version: String,
    pub created_utc: String,
    pub generator: String,
    pub files: BTreeMap<String, ManifestEntry>,
}

/// Current UTC time as `YYYY-MM-DDTHH:MM:SS+00:00`, mirroring Python's
/// `datetime.now(timezone.utc).isoformat(timespec="seconds")`.
/// Implemented without a date crate (Howard Hinnant's civil-from-days).
pub fn utc_now_iso8601() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let (y, m, d) = civil_from_days((secs / 86400) as i64);
    let (hh, mm, ss) = ((secs / 3600) % 24, (secs / 60) % 60, secs % 60);
    format!("{y:04}-{m:02}-{d:02}T{hh:02}:{mm:02}:{ss:02}+00:00")
}

fn civil_from_days(z: i64) -> (i64, i64, i64) {
    let z = z + 719468;
    let era = z.div_euclid(146097);
    let doe = z.rem_euclid(146097);
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    (if m <= 2 { y + 1 } else { y }, m, d)
}

/// Build the manifest for a dataset directory.
///
/// Every `*.jsonl` file in the directory root is a case file (validated
/// and counted); `CANARY.txt` is hashed as an artifact. `manifest.json`
/// itself is never included.
pub fn build_manifest(
    dataset_dir: &Path,
    dataset_version: &str,
    dataset_name: &str,
    peira_version: &str,
) -> Result<Manifest, String> {
    if !dataset_dir.is_dir() {
        return Err(format!(
            "dataset directory {} not found",
            dataset_dir.display()
        ));
    }
    let mut names: Vec<String> = fs::read_dir(dataset_dir)
        .map_err(|e| format!("cannot read dataset dir: {e}"))?
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| p.is_file())
        .filter_map(|p| {
            p.file_name()
                .and_then(|n| n.to_str())
                .map(|s| s.to_string())
        })
        .filter(|n| n != MANIFEST_NAME)
        .collect();
    names.sort();
    let mut files = BTreeMap::new();
    for name in names {
        let path = dataset_dir.join(&name);
        if name.ends_with(CASE_SUFFIX) {
            let summary = summarize_cases(&path)?;
            files.insert(
                name,
                ManifestEntry {
                    kind: "cases".into(),
                    sha256: sha256_file(&path).map_err(|e| format!("cannot hash {path:?}: {e}"))?,
                    n_cases: Some(summary.n_cases),
                    n_by_family: Some(summary.n_by_family),
                    n_by_severity: Some(summary.n_by_severity),
                    n_by_primitive: Some(summary.n_by_primitive),
                },
            );
        } else if name == CANARY_NAME {
            files.insert(
                name,
                ManifestEntry {
                    kind: "artifact".into(),
                    sha256: sha256_file(&path).map_err(|e| format!("cannot hash {path:?}: {e}"))?,
                    n_cases: None,
                    n_by_family: None,
                    n_by_severity: None,
                    n_by_primitive: None,
                },
            );
        }
    }
    let generator = if peira_version.is_empty() {
        "peira".to_string()
    } else {
        format!("peira {peira_version}")
    };
    Ok(Manifest {
        dataset: dataset_name.into(),
        dataset_version: dataset_version.into(),
        created_utc: utc_now_iso8601(),
        generator,
        files,
    })
}

/// Read and minimally validate `manifest.json`.
pub fn read_manifest(dataset_dir: &Path) -> Result<Manifest, String> {
    let path = dataset_dir.join(MANIFEST_NAME);
    if !path.is_file() {
        return Err(format!("no {MANIFEST_NAME} in {}", dataset_dir.display()));
    }
    let text =
        fs::read_to_string(&path).map_err(|e| format!("cannot read {MANIFEST_NAME}: {e}"))?;
    serde_json::from_str(&text).map_err(|e| format!("{MANIFEST_NAME} is not valid JSON ({e})"))
}

/// Python-style `repr` for small JSON values, for mismatch messages.
fn py_repr(v: &Value) -> String {
    match v {
        Value::String(s) => format!("'{s}'"),
        Value::Null => "None".into(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        Value::Array(items) => {
            format!(
                "[{}]",
                items.iter().map(py_repr).collect::<Vec<_>>().join(", ")
            )
        }
        Value::Object(map) => {
            let inner = map
                .iter()
                .map(|(k, val)| format!("'{k}': {}", py_repr(val)))
                .collect::<Vec<_>>()
                .join(", ");
            format!("{{{inner}}}")
        }
        _ => v.to_string(),
    }
}

/// Check a dataset directory against its `manifest.json`.
///
/// Returns mismatch descriptions; empty means the directory matches the
/// manifest exactly. Message strings mirror the Python reference.
pub fn verify_manifest(dataset_dir: &Path) -> Result<Vec<String>, String> {
    let manifest = read_manifest(dataset_dir)?;
    let mut errors = Vec::new();
    for (name, entry) in &manifest.files {
        let path = dataset_dir.join(name);
        if !path.is_file() {
            errors.push(format!("{name}: listed in manifest but missing on disk"));
            continue;
        }
        let actual = sha256_file(&path).map_err(|e| format!("cannot hash {name}: {e}"))?;
        if actual != entry.sha256 {
            let m12: String = entry.sha256.chars().take(12).collect();
            let d12: String = actual.chars().take(12).collect();
            errors.push(format!(
                "{name}: sha256 mismatch (manifest {m12}…, disk {d12}…)"
            ));
            continue;
        }
        if entry.kind == "cases" {
            let summary = match summarize_cases(&path) {
                Ok(s) => s,
                Err(e) => {
                    errors.push(format!("{name}: {e}"));
                    continue;
                }
            };
            let disk = serde_json::to_value(&summary).unwrap_or(Value::Null);
            for key in ["n_cases", "n_by_family", "n_by_severity", "n_by_primitive"] {
                let manifest_v = match key {
                    "n_cases" => entry.n_cases.map(Value::from),
                    "n_by_family" => entry
                        .n_by_family
                        .as_ref()
                        .map(|m| serde_json::to_value(m).unwrap()),
                    "n_by_severity" => entry
                        .n_by_severity
                        .as_ref()
                        .map(|m| serde_json::to_value(m).unwrap()),
                    _ => entry
                        .n_by_primitive
                        .as_ref()
                        .map(|m| serde_json::to_value(m).unwrap()),
                };
                if manifest_v.as_ref() != disk.get(key) {
                    errors.push(format!(
                        "{name}: {key} changed (manifest {}, disk {})",
                        manifest_v
                            .map(|v| py_repr(&v))
                            .unwrap_or_else(|| "None".into()),
                        py_repr(disk.get(key).unwrap_or(&Value::Null)),
                    ));
                }
            }
        }
    }
    Ok(errors)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn write_tmp(name: &str, contents: &str) -> (tempfile::TempDir, PathBuf) {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join(name);
        let mut f = fs::File::create(&path).unwrap();
        f.write_all(contents.as_bytes()).unwrap();
        (dir, path)
    }

    const CASE: &str = r#"{"case_id":"c1","family":"indirection","primitive":"choice","severity":"low","benign":{"input":{},"expected_decision":"a"},"attacked":{"input":{}}}"#;

    #[test]
    fn civil_from_days_known_dates() {
        assert_eq!(civil_from_days(0), (1970, 1, 1));
        assert_eq!(civil_from_days(20343), (2025, 9, 12));
    }

    #[test]
    fn utc_now_format() {
        let s = utc_now_iso8601();
        assert!(s.len() == 25 && s.ends_with("+00:00") && s.contains('T'));
    }

    #[test]
    fn summarize_counts() {
        let (_dir, path) = write_tmp("c.jsonl", &format!("{CASE}\n{CASE}\n"));
        let s = summarize_cases(&path).unwrap();
        assert_eq!(s.n_cases, 2);
        assert_eq!(s.n_by_family["indirection"], 2);
    }

    #[test]
    fn summarize_reports_all_problems() {
        let (_dir, path) = write_tmp("c.jsonl", "{bad json\n{\"case_id\": 1}\n");
        let err = summarize_cases(&path).unwrap_err();
        assert!(err.contains("c.jsonl:1: invalid JSON"));
        assert!(err.contains("c.jsonl:2: missing required key"));
    }

    #[test]
    fn sha256_known() {
        let (_dir, path) = write_tmp("f.txt", "abc");
        assert_eq!(
            sha256_file(&path).unwrap(),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }
}
