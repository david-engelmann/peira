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

use crate::py_repr::py_repr_value;
use crate::schema::{validate_case_dict, Case};

pub const MANIFEST_NAME: &str = "manifest.json";
pub const CANARY_NAME: &str = "CANARY.txt";
pub const CASE_SUFFIX: &str = ".jsonl";

/// The canonical case-file predicate.
///
/// A case file is a regular file (following symlinks) whose name ends in
/// `.jsonl`. This ONE predicate is the security invariant behind manifest
/// completeness: the runner, `build_manifest`, and the manifest sweep must
/// all agree on what a case file is, or an unlisted file could be scored
/// but never flagged. (An `extension()` check is the wrong test here: a
/// file named exactly `.jsonl` has no extension yet must count; a
/// `DirEntry::file_type()` check is wrong too — it does not follow
/// symlinks, while the runner scores through them.)
pub fn is_case_file(path: &Path) -> bool {
    path.is_file()
        && path
            .file_name()
            .and_then(|n| n.to_str())
            .map(|n| n.ends_with(CASE_SUFFIX))
            .unwrap_or(false)
}

/// Maximum run of leading `[` / `{` characters accepted in one case-file
/// line before parsing.
///
/// Deeper nesting is rejected with a clear error instead of reaching the
/// parser: unbounded nesting recurses in the JSON parser and again in
/// the canonical serializer, so case files stay shallow by construction.
/// The cap sits far above any realistic case (and above serde_json's own
/// 128-level recursion limit, which remains as a second line of defense),
/// so legitimate files never trip it. Documented in docs/Dataset.md.
pub const MAX_JSON_NESTING: usize = 256;

/// Reject a case-file line whose leading bracket run exceeds
/// [`MAX_JSON_NESTING`]. Called before `serde_json::from_str` on every
/// line read by [`iter_case_lines`] and [`summarize_cases`].
fn check_line_nesting(line: &str) -> Result<(), String> {
    let depth = line
        .trim_start()
        .chars()
        .take_while(|c| *c == '[' || *c == '{')
        .count();
    if depth > MAX_JSON_NESTING {
        return Err(format!(
            "nesting depth {depth} exceeds the {MAX_JSON_NESTING}-level cap"
        ));
    }
    Ok(())
}

/// Parse one case-file line: the nesting cap is checked before the
/// line reaches the JSON parser.
fn parse_case_line(line: &str) -> Result<Value, String> {
    check_line_nesting(line)?;
    serde_json::from_str(line).map_err(|e| e.to_string())
}

/// One non-blank line of a case file: the parsed JSON or the parse error.
pub struct CaseLine {
    pub path: PathBuf,
    pub lineno: usize,
    pub result: Result<Value, String>,
}

/// Read and collect every non-blank line of every case file (see
/// [`is_case_file`]) in the dataset directory root, in sorted filename
/// order.
///
/// Eager, not lazy, despite the `iter_` name: I/O errors surface up
/// front as `io::Result`, and every caller needs the full line list
/// anyway. (The name mirrors the Python `iter_case_lines` generator.)
///
/// A JSON syntax error is reported per line (not raised): serde_json's
/// message differs in wording from Python's `json.JSONDecodeError`, so the
/// `invalid JSON (...)` text is close but not byte-identical across
/// languages.
pub fn iter_case_lines(dataset_dir: &Path) -> io::Result<Vec<CaseLine>> {
    let mut paths: Vec<PathBuf> = fs::read_dir(dataset_dir)?
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| is_case_file(p))
        .collect();
    paths.sort();
    let mut out = Vec::new();
    for path in paths {
        let text = fs::read_to_string(&path)?;
        for (lineno, line) in text.lines().enumerate() {
            if line.trim().is_empty() {
                continue;
            }
            let result = parse_case_line(line).map_err(|e| format!("invalid JSON ({e})"));
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
    summarize_cases_hashed(path).map(|(summary, _digest)| summary)
}

/// Validate a JSONL case file, count its cases, and hash its bytes.
///
/// The file is read exactly once: the SHA-256 and the parse share the
/// single read instead of a hash pass plus a parse pass (2x I/O and 2x
/// JSON work per file in the old code).
pub fn summarize_cases_hashed(path: &Path) -> Result<(CaseSummary, String), String> {
    let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
    let bytes = fs::read(path).map_err(|e| format!("cannot read {name}: {e}"))?;
    summarize_case_bytes(name, &bytes)
}

/// Validate JSONL case bytes, count the cases, and hash the bytes.
///
/// The SHA-256 and the parse share the single buffer: callers that
/// already hold the bytes (verification) never re-read the file.
pub fn summarize_case_bytes(name: &str, bytes: &[u8]) -> Result<(CaseSummary, String), String> {
    let mut h = Sha256::new();
    h.update(bytes);
    let digest = format!("{:x}", h.finalize());
    let text = std::str::from_utf8(bytes).map_err(|e| format!("cannot read {name}: {e}"))?;
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
        let case: Value = match parse_case_line(line) {
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
    Ok((summary, digest))
}

/// One entry in a manifest's `files` section.
///
/// `kind` and `sha256` default on read: Python's `read_manifest`
/// "minimally validates" (it only requires the `files` section), so a
/// hand-written manifest the Python side accepts must also parse here —
/// a missing digest reports as a mismatch, not a parse failure.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ManifestEntry {
    #[serde(default)]
    pub kind: String,
    #[serde(default)]
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
///
/// The metadata fields default on read: Python's `read_manifest`
/// "minimally validates" (it only requires the `files` section), so a
/// hand-written manifest the Python side accepts must also parse here.
/// `files` stays required on both sides.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Manifest {
    #[serde(default)]
    pub dataset: String,
    #[serde(default)]
    pub dataset_version: String,
    #[serde(default)]
    pub created_utc: String,
    #[serde(default)]
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
/// Every case file in the directory root (see [`is_case_file`]) is
/// validated and counted; `CANARY.txt` is hashed as an artifact.
/// `manifest.json` itself is never included.
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
        if is_case_file(&path) {
            // One read per file: summarize and hash share the bytes.
            let (summary, digest) = summarize_cases_hashed(&path)?;
            files.insert(
                name,
                ManifestEntry {
                    kind: "cases".into(),
                    sha256: digest,
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

/// Typed errors from [`read_manifest`], so callers (notably the CLI)
/// can discriminate "no manifest" from "unreadable manifest" without
/// string-matching the core's error text.
#[derive(Debug, Clone, PartialEq)]
pub enum ManifestError {
    /// No `manifest.json` in the directory.
    NotFound { dir: PathBuf },
    /// `manifest.json` exists but could not be read.
    Unreadable { reason: String },
    /// `manifest.json` is not valid JSON or has the wrong shape.
    Invalid { reason: String },
}

impl std::fmt::Display for ManifestError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ManifestError::NotFound { dir } => {
                write!(f, "no {MANIFEST_NAME} in {}", dir.display())
            }
            ManifestError::Unreadable { reason } => {
                write!(f, "cannot read {MANIFEST_NAME}: {reason}")
            }
            ManifestError::Invalid { reason } => write!(f, "{reason}"),
        }
    }
}

impl std::error::Error for ManifestError {}

/// Read `manifest.json`, returning the parsed manifest and the SHA-256
/// hex digest of the manifest bytes.
///
/// The file is read exactly once: the digest is computed over the same
/// buffer that is parsed, so a manifest swapped between a verify pass
/// and a re-read can never seal unverified bytes into an analysis lock.
/// (The Python side mirrors this: `verify_manifest_sealed` in
/// `python/peira/dataset.py`.)
pub fn read_manifest(dataset_dir: &Path) -> Result<(Manifest, String), ManifestError> {
    let path = dataset_dir.join(MANIFEST_NAME);
    if !path.is_file() {
        return Err(ManifestError::NotFound {
            dir: dataset_dir.to_path_buf(),
        });
    }
    let bytes = fs::read(&path).map_err(|e| ManifestError::Unreadable {
        reason: e.to_string(),
    })?;
    let mut h = Sha256::new();
    h.update(&bytes);
    let digest = format!("{:x}", h.finalize());
    let v: Value = serde_json::from_slice(&bytes).map_err(|e| ManifestError::Invalid {
        reason: format!("{MANIFEST_NAME} is not valid JSON ({e})"),
    })?;
    // Python's read_manifest only requires the `files` section; report
    // its absence with the same message rather than serde's
    // "missing field `files`".
    if v.get("files").is_none() {
        return Err(ManifestError::Invalid {
            reason: format!("{MANIFEST_NAME} is missing the 'files' section"),
        });
    }
    let manifest: Manifest = serde_json::from_value(v).map_err(|e| ManifestError::Invalid {
        reason: format!("{MANIFEST_NAME} is not valid JSON ({e})"),
    })?;
    Ok((manifest, digest))
}

/// A manifest file name is caller-controlled input to the verifier: the
/// manifest names files and `verify_manifest` hashes them. Reject `..`,
/// path separators, and absolute paths before touching the filesystem —
/// `dataset_dir.join("..")` would otherwise escape the dataset root.
/// (Conservative: a literally-on-disk `a..b.jsonl` trips this too, but
/// case files are `<id>.jsonl` and never look like that.)
fn is_unsafe_manifest_name(name: &str) -> bool {
    name.is_empty()
        || name.contains("..")
        || name.contains('/')
        || name.contains('\\')
        || Path::new(name).is_absolute()
}

/// Check a dataset directory against its `manifest.json`.
///
/// Returns mismatch descriptions; empty means the directory matches the
/// manifest exactly. Message strings mirror the Python reference.
/// Verify a dataset directory against its `manifest.json`.
///
/// Every file is read exactly once: the digest and (for case files) the
/// parse share the same bytes, so verification can never hash one
/// version of a file and summarize another.
pub fn verify_manifest(dataset_dir: &Path) -> Result<Vec<String>, ManifestError> {
    let (manifest, _digest) = read_manifest(dataset_dir)?;
    let mut errors = Vec::new();
    for (name, entry) in &manifest.files {
        if is_unsafe_manifest_name(name) {
            errors.push(format!(
                "{name}: unsafe file name in manifest \
                 (path separators, '..', and absolute paths are not allowed)"
            ));
            continue;
        }
        let path = dataset_dir.join(name);
        if !path.is_file() {
            errors.push(format!("{name}: listed in manifest but missing on disk"));
            continue;
        }
        // Single read: the digest and the parse below share these bytes.
        let bytes = fs::read(&path).map_err(|e| ManifestError::Unreadable {
            reason: format!("cannot read {name}: {e}"),
        })?;
        let mut h = Sha256::new();
        h.update(&bytes);
        let actual = format!("{:x}", h.finalize());
        if actual != entry.sha256 {
            let m12: String = entry.sha256.chars().take(12).collect();
            let d12: String = actual.chars().take(12).collect();
            errors.push(format!(
                "{name}: sha256 mismatch (manifest {m12}…, disk {d12}…)"
            ));
            continue;
        }
        if entry.kind == "cases" {
            let summary = match summarize_case_bytes(name, &bytes) {
                Ok((s, _)) => s,
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
                            .map(|v| py_repr_value(&v))
                            .unwrap_or_else(|| "None".into()),
                        py_repr_value(disk.get(key).unwrap_or(&Value::Null)),
                    ));
                }
            }
        }
    }
    // P0: files build_manifest would include (case files — see
    // is_case_file — and CANARY.txt) that are on disk but not listed
    // must be flagged — otherwise unlisted case files would be silently
    // unscored, and the "directory matches the manifest exactly"
    // guarantee would be false. Names are compared as strings only;
    // unlisted files are never opened, so unsafe on-disk names cannot
    // escape the directory. is_file() follows symlinks, matching the
    // runner and build_manifest: a symlinked case file is scored, so
    // the sweep must see it too.
    let listed: std::collections::HashSet<&str> =
        manifest.files.keys().map(|s| s.as_str()).collect();
    let mut on_disk: Vec<String> = Vec::new();
    let read_dir = fs::read_dir(dataset_dir).map_err(|e| ManifestError::Unreadable {
        reason: format!("cannot list {}: {e}", dataset_dir.display()),
    })?;
    for entry in read_dir {
        let entry = entry.map_err(|e| ManifestError::Unreadable {
            reason: format!("cannot list {}: {e}", dataset_dir.display()),
        })?;
        let name = entry.file_name().to_string_lossy().into_owned();
        if name == MANIFEST_NAME {
            continue;
        }
        let path = entry.path();
        if !(is_case_file(&path) || (name == CANARY_NAME && path.is_file())) {
            continue;
        }
        on_disk.push(name);
    }
    on_disk.sort();
    for name in on_disk {
        if !listed.contains(name.as_str()) {
            errors.push(format!("{name}: on disk but not listed in manifest"));
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
    fn nesting_cap_rejects_deep_lines_before_parsing() {
        let deep = "[".repeat(MAX_JSON_NESTING + 1);
        let (_dir, path) = write_tmp("deep.jsonl", &deep);
        let err = summarize_cases(&path).unwrap_err();
        assert!(
            err.contains("exceeds the 256-level cap"),
            "unexpected error: {err}"
        );
        // Leading whitespace doesn't hide the run.
        let padded = format!("  {}", "[".repeat(MAX_JSON_NESTING + 10));
        let (_dir, path) = write_tmp("padded.jsonl", &padded);
        let err = summarize_cases(&path).unwrap_err();
        assert!(err.contains("exceeds the 256-level cap"), "{err}");
    }

    #[test]
    fn nesting_at_cap_reaches_the_parser() {
        // Exactly at the cap the line is handed to serde_json, whose own
        // 128-level recursion limit rejects it with a parser error —
        // proving the cap didn't fire first.
        let at_cap = "[".repeat(MAX_JSON_NESTING);
        let (_dir, path) = write_tmp("atcap.jsonl", &at_cap);
        let err = summarize_cases(&path).unwrap_err();
        assert!(err.contains("invalid JSON"), "{err}");
        assert!(!err.contains("level cap"), "{err}");
        // Ordinary nesting is untouched.
        assert!(check_line_nesting("{\"a\": [1, {\"b\": 2}]}").is_ok());
    }

    #[test]
    fn sha256_known() {
        let (_dir, path) = write_tmp("f.txt", "abc");
        assert_eq!(
            sha256_file(&path).unwrap(),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }

    #[test]
    fn read_manifest_accepts_minimal_shape_like_python() {
        // Python's read_manifest only requires the `files` section; the
        // Rust side must accept the same minimal manifest. Metadata
        // fields default to empty strings on both sides.
        let dir = tempfile::tempdir().unwrap();
        let content = r#"{"files": {}}"#;
        fs::write(dir.path().join("manifest.json"), content).unwrap();
        let (m, digest) = read_manifest(dir.path()).unwrap();
        assert!(m.files.is_empty());
        assert_eq!(m.dataset, "");
        assert_eq!(m.dataset_version, "");
        // The digest is over the manifest bytes, read once.
        let mut h = Sha256::new();
        h.update(content.as_bytes());
        assert_eq!(digest, format!("{:x}", h.finalize()));
    }

    #[test]
    fn read_manifest_rejects_missing_files_section_like_python() {
        let dir = tempfile::tempdir().unwrap();
        fs::write(dir.path().join("manifest.json"), r#"{"dataset": "x"}"#).unwrap();
        let err = read_manifest(dir.path()).unwrap_err();
        assert_eq!(
            err.to_string(),
            "manifest.json is missing the 'files' section"
        );
    }

    #[test]
    fn read_manifest_not_found_is_typed() {
        let dir = tempfile::tempdir().unwrap();
        let err = read_manifest(dir.path()).unwrap_err();
        assert!(matches!(err, ManifestError::NotFound { .. }));
        assert!(err.to_string().starts_with("no manifest.json in "));
    }

    #[test]
    fn verify_manifest_rejects_unsafe_names() {
        // A manifest entry for `../escape.jsonl` must not hash a file
        // outside the dataset root — it is reported, not followed.
        let dir = tempfile::tempdir().unwrap();
        for evil in [
            "../escape.jsonl",
            "sub/dir.jsonl",
            "/abs.jsonl",
            "a..b.jsonl",
        ] {
            let manifest =
                format!(r#"{{"files": {{"{evil}": {{"kind": "cases", "sha256": "0"}}}}}}"#);
            fs::write(dir.path().join("manifest.json"), manifest).unwrap();
            let errors = verify_manifest(dir.path()).unwrap();
            assert_eq!(errors.len(), 1, "for {evil}");
            assert!(
                errors[0].contains("unsafe file name in manifest"),
                "for {evil}: {}",
                errors[0]
            );
        }
    }

    #[test]
    fn summarize_cases_hashed_matches_separate_hash() {
        // The single-read hash must equal hashing the file separately.
        let (_dir, path) = write_tmp("c.jsonl", &format!("{CASE}\n"));
        let (summary, digest) = summarize_cases_hashed(&path).unwrap();
        assert_eq!(summary.n_cases, 1);
        assert_eq!(digest, sha256_file(&path).unwrap());
    }

    #[test]
    fn verify_manifest_modified_file_reports_mismatch_not_parse_error() {
        // Hash-before-parse from the same bytes: a modified file reports a
        // digest mismatch and is never parsed, so garbage bytes that could
        // not parse still surface as exactly one mismatch error.
        let dir = tempfile::tempdir().unwrap();
        fs::write(dir.path().join("c.jsonl"), format!("{CASE}\n")).unwrap();
        let manifest = build_manifest(dir.path(), "1.0.0", "d", "0.1.0").unwrap();
        fs::write(
            dir.path().join("manifest.json"),
            serde_json::to_string(&manifest).unwrap(),
        )
        .unwrap();
        fs::write(dir.path().join("c.jsonl"), b"\x00\x01not json at all\xff\n").unwrap();
        let errors = verify_manifest(dir.path()).unwrap();
        assert_eq!(errors.len(), 1, "{errors:?}");
        assert!(errors[0].contains("sha256 mismatch"), "{}", errors[0]);
        assert!(!errors[0].contains("invalid JSON"), "{}", errors[0]);
    }

    #[test]
    fn verify_manifest_entry_without_sha256_is_mismatch() {
        // A hand-written entry missing `sha256` (Python tolerates it)
        // parses via the serde defaults and reports a mismatch.
        let dir = tempfile::tempdir().unwrap();
        fs::write(dir.path().join("c.jsonl"), format!("{CASE}\n")).unwrap();
        fs::write(
            dir.path().join("manifest.json"),
            r#"{"files": {"c.jsonl": {"kind": "cases"}}}"#,
        )
        .unwrap();
        let errors = verify_manifest(dir.path()).unwrap();
        assert_eq!(errors.len(), 1, "{errors:?}");
        assert!(errors[0].contains("sha256 mismatch"), "{}", errors[0]);
    }

    #[test]
    fn verify_manifest_flags_unlisted_case_file() {
        // P0: a case file added after the manifest was built must be
        // flagged — otherwise it would be silently unscored and the
        // "directory matches the manifest exactly" guarantee would lie.
        let dir = tempfile::tempdir().unwrap();
        fs::write(dir.path().join("c.jsonl"), format!("{CASE}\n")).unwrap();
        let manifest = build_manifest(dir.path(), "1.0.0", "d", "0.1.0").unwrap();
        fs::write(
            dir.path().join("manifest.json"),
            serde_json::to_string(&manifest).unwrap(),
        )
        .unwrap();
        assert!(verify_manifest(dir.path()).unwrap().is_empty());
        // Unlisted case file and canary are flagged; a non-case file is
        // ignored, mirroring build_manifest's inclusion rule.
        fs::write(dir.path().join("extra.jsonl"), format!("{CASE}\n")).unwrap();
        fs::write(dir.path().join("CANARY.txt"), "canary\n").unwrap();
        fs::write(dir.path().join("notes.md"), "not a case file\n").unwrap();
        let errors = verify_manifest(dir.path()).unwrap();
        assert_eq!(errors.len(), 2, "{errors:?}");
        assert!(
            errors
                .iter()
                .any(|e| e == "extra.jsonl: on disk but not listed in manifest"),
            "{errors:?}"
        );
        assert!(
            errors
                .iter()
                .any(|e| e == "CANARY.txt: on disk but not listed in manifest"),
            "{errors:?}"
        );
    }

    #[test]
    fn read_manifest_rejects_malformed_files_shape() {
        // {"files": [...]} / {"files": null} / non-object entries must
        // be clean typed errors, not a panic or a silent accept —
        // mirroring the Python _read_manifest_sealed isinstance checks.
        let dir = tempfile::tempdir().unwrap();
        for bad in [
            r#"{"files": []}"#,
            r#"{"files": null}"#,
            r#"{"files": {"c.jsonl": "nope"}}"#,
            r#"{"files": {"c.jsonl": 42}}"#,
        ] {
            fs::write(dir.path().join("manifest.json"), bad).unwrap();
            let err = read_manifest(dir.path()).unwrap_err();
            assert!(
                matches!(err, ManifestError::Invalid { .. }),
                "for {bad}: {err:?}"
            );
        }
    }

    #[test]
    #[cfg(unix)]
    fn verify_manifest_flags_unlisted_symlinked_case_file() {
        // P1: the sweep must follow symlinks — the runner scores through
        // them, so an unlisted symlinked case file would be scored but
        // never flagged. (Unix-only: creating symlinks needs privileges
        // on Windows.)
        let dir = tempfile::tempdir().unwrap();
        fs::write(dir.path().join("c.jsonl"), format!("{CASE}\n")).unwrap();
        let manifest = build_manifest(dir.path(), "1.0.0", "d", "0.1.0").unwrap();
        fs::write(
            dir.path().join("manifest.json"),
            serde_json::to_string(&manifest).unwrap(),
        )
        .unwrap();
        assert!(verify_manifest(dir.path()).unwrap().is_empty());
        std::os::unix::fs::symlink("c.jsonl", dir.path().join("evil.jsonl")).unwrap();
        let errors = verify_manifest(dir.path()).unwrap();
        assert!(
            errors
                .iter()
                .any(|e| e == "evil.jsonl: on disk but not listed in manifest"),
            "{errors:?}"
        );
        // The runner scores through the link — that is exactly why the
        // sweep must flag it: scored ⟺ manifested ⟺ swept.
        assert_eq!(load_cases(dir.path()).unwrap().len(), 2);
    }

    #[test]
    fn dot_jsonl_file_is_a_case_file() {
        // A file named exactly ".jsonl" has no extension but its name
        // ends with ".jsonl": the runner scores it, so build and the
        // sweep must include it too (mirrors the Python predicate).
        let dir = tempfile::tempdir().unwrap();
        fs::write(dir.path().join("c.jsonl"), format!("{CASE}\n")).unwrap();
        fs::write(dir.path().join(".jsonl"), format!("{CASE}\n")).unwrap();
        let manifest = build_manifest(dir.path(), "1.0.0", "d", "0.1.0").unwrap();
        assert!(
            manifest.files.contains_key(".jsonl"),
            "{:?}",
            manifest.files.keys().collect::<Vec<_>>()
        );
        fs::write(
            dir.path().join("manifest.json"),
            serde_json::to_string(&manifest).unwrap(),
        )
        .unwrap();
        assert!(verify_manifest(dir.path()).unwrap().is_empty());
        assert_eq!(load_cases(dir.path()).unwrap().len(), 2);
    }

    #[test]
    fn summarize_case_bytes_matches_path_version() {
        // The bytes-based summarize (used by verification) agrees with
        // the path-based one on both digest and summary.
        let (_dir, path) = write_tmp("c.jsonl", &format!("{CASE}\n"));
        let bytes = fs::read(&path).unwrap();
        let (from_bytes, digest_bytes) = summarize_case_bytes("c.jsonl", &bytes).unwrap();
        let (from_path, digest_path) = summarize_cases_hashed(&path).unwrap();
        assert_eq!(digest_bytes, digest_path);
        assert_eq!(from_bytes, from_path);
    }
}
