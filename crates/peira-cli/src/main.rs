//! peira-cli: thin Rust CLI for peira dataset validation in CI.
//!
//! Two subcommands, both read-only:
//!
//! - `validate --dir <dir>`: schema-validate every case in a dataset
//!   directory (the G1 authoring gate, in Rust for CI speed).
//! - `verify-manifest --dir <dir>`: verify the directory against its
//!   `manifest.json`.
//!
//! Exit codes mirror the Python CLI: 0 = ok, 1 = validation/user error,
//! 2 = usage error.

use peira_core::dataset::{iter_case_lines, read_manifest, verify_manifest, MANIFEST_NAME};
use peira_core::schema::validate_case_dict;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

const EXIT_OK: u8 = 0;
const EXIT_USER_ERROR: u8 = 1;
const EXIT_USAGE: u8 = 2;

fn usage() -> String {
    format!(
        "peira-cli {version} — dataset validation for CI\n\
         \n\
         Usage:\n  \
           peira-cli validate --dir <dataset-dir>\n  \
           peira-cli verify-manifest --dir <dataset-dir>\n\
         \n\
         Options:\n  \
           --dir <path>   dataset directory to check\n  \
           -h, --help     show this help\n  \
           -V, --version  show the version",
        version = peira_core::VERSION,
    )
}

fn cmd_validate(dir: &Path) -> u8 {
    if !dir.is_dir() {
        eprintln!("error: dataset directory {} not found", dir.display());
        return EXIT_USER_ERROR;
    }
    let lines = match iter_case_lines(dir) {
        Ok(l) => l,
        Err(e) => {
            eprintln!("error: cannot read dataset directory: {e}");
            return EXIT_USER_ERROR;
        }
    };
    let mut n_cases = 0;
    let mut n_errors = 0;
    for line in &lines {
        n_cases += 1;
        let name = line
            .path
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("?");
        let d = match &line.result {
            Ok(d) => d,
            Err(e) => {
                println!("{name}:{}: {e}", line.lineno);
                n_errors += 1;
                continue;
            }
        };
        let errors = validate_case_dict(d);
        if !errors.is_empty() {
            println!("{name}:{}: {}", line.lineno, errors.join("; "));
            n_errors += 1;
        }
    }
    if n_errors > 0 {
        println!("validate: FAILED ({n_errors} errors in {n_cases} cases)");
        EXIT_USER_ERROR
    } else {
        println!("validate: OK ({n_cases} cases)");
        EXIT_OK
    }
}

fn cmd_verify_manifest(dir: &Path) -> u8 {
    if !dir.is_dir() {
        eprintln!("error: dataset directory {} not found", dir.display());
        return EXIT_USER_ERROR;
    }
    // Distinguish "no manifest" from "unreadable manifest" for the same
    // messages the Python CLI emits.
    if let Err(e) = read_manifest(dir) {
        if e.starts_with(&format!("no {MANIFEST_NAME}")) {
            eprintln!(
                "error: no {MANIFEST_NAME} in {} — run \
                 'peira dataset build-manifest' first",
                dir.display()
            );
        } else {
            eprintln!("error: unreadable manifest: {e}");
        }
        return EXIT_USER_ERROR;
    }
    let errors = match verify_manifest(dir) {
        Ok(e) => e,
        Err(e) => {
            eprintln!("error: unreadable manifest: {e}");
            return EXIT_USER_ERROR;
        }
    };
    if !errors.is_empty() {
        eprintln!("error: {} does not match {MANIFEST_NAME}:", dir.display());
        for e in &errors {
            eprintln!("  - {e}");
        }
        return EXIT_USER_ERROR;
    }
    println!("manifest ok: {} matches {MANIFEST_NAME}", dir.display());
    EXIT_OK
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args
        .iter()
        .any(|a| a == "-h" || a == "--help" || a == "help")
    {
        println!("{}", usage());
        return ExitCode::from(EXIT_OK);
    }
    if args.iter().any(|a| a == "-V" || a == "--version") {
        println!("peira-cli {}", peira_core::VERSION);
        return ExitCode::from(EXIT_OK);
    }
    let (cmd, rest) = match args.split_first() {
        Some((c, r)) => (c.as_str(), r),
        None => {
            eprintln!("{}", usage());
            return ExitCode::from(EXIT_USAGE);
        }
    };
    if !matches!(cmd, "validate" | "verify-manifest") {
        eprintln!("error: unknown command '{cmd}'\n\n{}", usage());
        return ExitCode::from(EXIT_USAGE);
    }
    // Parse --dir <path> (only accepted option).
    let mut dir: Option<PathBuf> = None;
    let mut it = rest.iter().peekable();
    while let Some(a) = it.next() {
        if a == "--dir" {
            match it.next() {
                Some(v) => dir = Some(PathBuf::from(v)),
                None => {
                    eprintln!("error: --dir needs a value\n\n{}", usage());
                    return ExitCode::from(EXIT_USAGE);
                }
            }
        } else {
            eprintln!("error: unknown option '{a}'\n\n{}", usage());
            return ExitCode::from(EXIT_USAGE);
        }
    }
    let dir = match dir {
        Some(d) => d,
        None => {
            eprintln!("error: --dir is required\n\n{}", usage());
            return ExitCode::from(EXIT_USAGE);
        }
    };
    let code = match cmd {
        "validate" => cmd_validate(&dir),
        _ => cmd_verify_manifest(&dir),
    };
    ExitCode::from(code)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::io::Write;

    const CASE: &str = r#"{"case_id":"c1","family":"indirection","primitive":"choice","severity":"low","benign":{"input":{},"expected_decision":"a"},"attacked":{"input":{}}}"#;

    fn tmp_dataset(lines: &str) -> (tempfile::TempDir, PathBuf) {
        let dir = tempfile::tempdir().unwrap();
        let mut f = fs::File::create(dir.path().join("cases.jsonl")).unwrap();
        f.write_all(lines.as_bytes()).unwrap();
        let dir_path = dir.path().to_path_buf();
        // Leak the TempDir path ownership pattern: return both.
        (dir, dir_path)
    }

    #[test]
    fn validate_ok_and_failed() {
        let (_tmp, dir) = tmp_dataset(&format!("{CASE}\n"));
        assert_eq!(cmd_validate(&dir), EXIT_OK);
        let (_tmp, dir2) = tmp_dataset("{not json\n");
        assert_eq!(cmd_validate(&dir2), EXIT_USER_ERROR);
        let (_tmp, dir3) = tmp_dataset("{\"case_id\": 1}\n");
        assert_eq!(cmd_validate(&dir3), EXIT_USER_ERROR);
    }

    #[test]
    fn validate_missing_dir() {
        assert_eq!(
            cmd_validate(&PathBuf::from("/nonexistent-xyz")),
            EXIT_USER_ERROR
        );
    }
}
