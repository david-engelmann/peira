//! peira CLI (Rust): the empirical trial for decision models.
//!
//! Mirrors `python/peira/cli.py` command-for-command. Exit codes:
//! 0 clean, 1 user error (bad config/adapter), 2 infrastructure error,
//! 3 run completed but ranking-ineligible.

use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

use clap::{Parser, Subcommand};
use peira_core::adapter_protocol::SubprocessAdapter;
use peira_core::artifacts::RunArtifact;
use peira_core::metrics::PerCaseResult;
use peira_core::runner::{self, Adapter, MockAdapter, RunOptions, DEFAULT_ADAPTER_TIMEOUT};
use peira_core::schema::validate_case_dict;

const EXIT_OK: u8 = 0;
const EXIT_USER_ERROR: u8 = 1;
const EXIT_INFRA_ERROR: u8 = 2;
const EXIT_GATE_NOTE: u8 = 3;

#[derive(Parser)]
#[command(
    name = "peira",
    version = peira_core::VERSION,
    about = "The empirical trial for decision models."
)]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Run a suite through an adapter
    Run {
        /// Adapter: "mock", or a program on PATH / a path speaking the
        /// JSON adapter protocol (one JSON request per line on stdin,
        /// one JSON response per line on stdout).
        #[arg(long, default_value = "mock")]
        adapter: String,
        /// Pinned adapter version, recorded in the artifact and covered by
        /// the analysis lock. Defaults to "0.1.0" for the built-in mock;
        /// required for external (subprocess) adapters, since peira cannot
        /// infer the version of another program — pin it explicitly so the
        /// run is reproducible.
        #[arg(long)]
        adapter_version: Option<String>,
        /// Suite to run. "smoke" is an alias for "trial".
        #[arg(long, default_value = "trial-demo")]
        suite: String,
        /// Output directory for the run artifact
        #[arg(long, default_value = "runs")]
        out: PathBuf,
        /// Validate config without scoring
        #[arg(long)]
        dry_run: bool,
        /// Machine-readable progress on stdout
        #[arg(long)]
        json_progress: bool,
        /// Resume an interrupted run from its partial artifact
        #[arg(long)]
        resume: bool,
    },
    /// Validate a dataset directory
    Validate {
        #[arg(long)]
        dataset: PathBuf,
    },
    /// Render an HTML report from a run artifact
    Report {
        #[arg(long)]
        run: PathBuf,
        #[arg(long, default_value = "report.html")]
        out: PathBuf,
    },
    /// Verify a run artifact's analysis lock
    Verify {
        /// Path to the run artifact JSON
        #[arg(long)]
        run: PathBuf,
    },
}

/// Format an f64 like Python's repr: shortest round-trip, `.0` for whole
/// values, two-digit signed exponents (`1e-05`, `1e+21`).
fn py_num(x: f64) -> String {
    if x.is_nan() {
        return "nan".to_string();
    }
    if x.is_infinite() {
        return if x > 0.0 {
            "inf".to_string()
        } else {
            "-inf".to_string()
        };
    }
    let s = match serde_json::Number::from_f64(x) {
        Some(n) => n.to_string(),
        None => return "nan".to_string(),
    };
    if let Some(pos) = s.find('e') {
        let (mant, exp) = s.split_at(pos);
        let exp = &exp[1..];
        let (sign, digits) = match exp.strip_prefix('-') {
            Some(d) => ("-", d),
            None => ("+", exp.strip_prefix('+').unwrap_or(exp)),
        };
        let padded = if digits.len() < 2 {
            format!("{sign}{:0>2}", digits)
        } else {
            format!("{sign}{digits}")
        };
        return format!("{mant}e{padded}");
    }
    s
}

/// Format a JSON value like Python's `str()`: `True`/`False`/`None`,
/// `[a, b]` lists, Python-float numbers.
fn fmt_val(v: &serde_json::Value) -> String {
    match v {
        serde_json::Value::Null => "None".to_string(),
        serde_json::Value::Bool(b) => {
            if *b {
                "True".to_string()
            } else {
                "False".to_string()
            }
        }
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                i.to_string()
            } else if let Some(u) = n.as_u64() {
                u.to_string()
            } else {
                py_num(n.as_f64().unwrap_or(f64::NAN))
            }
        }
        serde_json::Value::String(s) => s.clone(),
        serde_json::Value::Array(a) => {
            format!("[{}]", a.iter().map(fmt_val).collect::<Vec<_>>().join(", "))
        }
        serde_json::Value::Object(_) => "{...}".to_string(),
    }
}

/// HTML-escape like Python's `html.escape(s, quote=True)`.
fn esc(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            '\'' => out.push_str("&#x27;"),
            c => out.push(c),
        }
    }
    out
}

fn lock16(lock: &str) -> String {
    lock.chars().take(16).collect()
}

fn which(name: &str) -> Option<PathBuf> {
    std::env::var_os("PATH").and_then(|paths| {
        std::env::split_paths(&paths).find_map(|dir| {
            let p = dir.join(name);
            if p.is_file() {
                Some(p)
            } else {
                None
            }
        })
    })
}

/// Resolve `--adapter` to a runnable adapter.
/// - `mock` → built-in deterministic mock (version "0.1.0" unless
///   `--adapter-version` overrides it)
/// - otherwise a program (path or on PATH) speaking the JSON adapter protocol
/// - Python dotted paths are rejected with a pointer to the Python CLI
///
/// External adapters cannot report their own version over the JSON protocol,
/// so `--adapter-version` is required for them: peira will not invent one.
fn resolve_adapter(
    name: &str,
    version_flag: Option<&str>,
) -> Result<(Box<dyn Adapter>, String, String), String> {
    if name == "mock" {
        return Ok((
            Box::new(MockAdapter::new()),
            "mock".to_string(),
            version_flag.unwrap_or("0.1.0").to_string(),
        ));
    }
    let Some(version) = version_flag else {
        return Err(format!(
            "external adapter '{name}' needs --adapter-version: peira cannot \
             infer the version of a subprocess, and an unpinned version makes \
             the run irreproducible"
        ));
    };
    if name.contains(':') {
        return Err(format!(
            "unknown adapter: '{name}' (the Rust CLI runs 'mock' and JSON-protocol \
             subprocess adapters; Python dotted paths need the Python CLI: \
             python -m peira.cli run --adapter '{name}')"
        ));
    }
    let is_path = name.contains('/') || name.starts_with('.');
    let on_path = which(name).is_some();
    if name.contains('.') && !is_path && !on_path {
        return Err(format!(
            "unknown adapter: '{name}' (looks like a Python dotted path, which needs \
             the Python CLI; the Rust CLI runs 'mock' and JSON-protocol subprocess adapters)"
        ));
    }
    if !is_path && !on_path {
        return Err(format!(
            "unknown adapter: '{name}' (available: mock, or a program on PATH speaking \
             the JSON adapter protocol)"
        ));
    }
    match SubprocessAdapter::spawn(name, &[], DEFAULT_ADAPTER_TIMEOUT) {
        Ok(a) => Ok((Box::new(a), name.to_string(), version.to_string())),
        Err(e) => Err(format!("cannot spawn adapter '{name}': {e}")),
    }
}

fn cmd_verify(run: &Path) -> u8 {
    if !run.exists() {
        eprintln!("error: {} not found", run.display());
        return EXIT_USER_ERROR;
    }
    let text = match fs::read_to_string(run) {
        Ok(t) => t,
        Err(e) => {
            eprintln!("error: cannot parse artifact: {e}");
            return EXIT_USER_ERROR;
        }
    };
    let artifact = match RunArtifact::from_json(&text) {
        Ok(a) => a,
        Err(e) => {
            eprintln!("error: cannot parse artifact: {e}");
            return EXIT_USER_ERROR;
        }
    };
    if artifact.verify() {
        println!("ok: {} — analysis lock valid", run.display());
        println!(
            "  adapter: {} ({}), suite: {}",
            artifact.adapter_name, artifact.adapter_version, artifact.suite
        );
        println!("  lock: {}...", lock16(&artifact.analysis_lock));
        EXIT_OK
    } else {
        eprintln!("FAIL: {} — analysis lock MISMATCH", run.display());
        eprintln!("  artifact was modified after sealing; metrics are not trustworthy");
        EXIT_USER_ERROR
    }
}

fn cmd_validate(dataset: &Path) -> u8 {
    if !dataset.exists() {
        eprintln!("error: {} not found", dataset.display());
        return EXIT_USER_ERROR;
    }
    let entries = match fs::read_dir(dataset) {
        Ok(e) => e,
        Err(e) => {
            eprintln!("error: cannot read {}: {e}", dataset.display());
            return EXIT_USER_ERROR;
        }
    };
    let mut jsonl: Vec<PathBuf> = entries
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.extension().and_then(|x| x.to_str()) == Some("jsonl"))
        .collect();
    jsonl.sort();
    let (mut n, mut bad) = (0u64, 0u64);
    for path in &jsonl {
        let content = match fs::read_to_string(path) {
            Ok(c) => c,
            Err(e) => {
                eprintln!("error: cannot read {}: {e}", path.display());
                return EXIT_INFRA_ERROR;
            }
        };
        for (lineno, line) in content.lines().enumerate() {
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            n += 1;
            let v: serde_json::Value = match serde_json::from_str(line) {
                Ok(v) => v,
                Err(e) => {
                    // Python's json.loads raises here → traceback → exit 2.
                    eprintln!(
                        "error: {}:{}: invalid JSON: {e}",
                        path.display(),
                        lineno + 1
                    );
                    return EXIT_INFRA_ERROR;
                }
            };
            let errors = validate_case_dict(&v);
            if !errors.is_empty() {
                bad += 1;
                println!("{}:{}: {}", path.display(), lineno + 1, errors.join("; "));
            }
        }
    }
    println!("validated {n} cases, {bad} invalid");
    if bad > 0 {
        EXIT_USER_ERROR
    } else {
        EXIT_OK
    }
}

fn cmd_report(run: &Path, out: &Path) -> u8 {
    if !run.exists() {
        eprintln!("error: {} not found", run.display());
        return EXIT_USER_ERROR;
    }
    let text = match fs::read_to_string(run) {
        Ok(t) => t,
        Err(e) => {
            eprintln!("error: cannot read {}: {e}", run.display());
            return EXIT_USER_ERROR;
        }
    };
    let artifact = match RunArtifact::from_json(&text) {
        Ok(a) => a,
        Err(e) => {
            eprintln!("error: cannot parse artifact: {e}");
            return EXIT_USER_ERROR;
        }
    };
    if !artifact.verify() {
        eprintln!("warning: analysis lock mismatch — artifact was modified after sealing.");
    }
    let m = &artifact.metrics;
    let mv = |k: &str| m.get(k).map(fmt_val).unwrap_or_default();
    let ci = |k: &str| -> (String, String) {
        match m.get(k).and_then(|v| v.as_array()) {
            Some(a) if a.len() == 2 => (fmt_val(&a[0]), fmt_val(&a[1])),
            _ => ("?".to_string(), "?".to_string()),
        }
    };
    let (asr_lo, asr_hi) = ci("asr_ci95");
    let (acc_lo, acc_hi) = ci("benign_accuracy_ci95");

    let mut row_list: Vec<String> = Vec::new();
    if let Some(pf) = m.get("per_family").and_then(|v| v.as_object()) {
        for (fam, v) in pf {
            let n = v.get("n").map(fmt_val).unwrap_or_default();
            let asr = v.get("asr").map(fmt_val).unwrap_or_default();
            let (lo, hi) = match v.get("asr_ci95").and_then(|x| x.as_array()) {
                Some(a) if a.len() == 2 => (fmt_val(&a[0]), fmt_val(&a[1])),
                _ => ("?".to_string(), "?".to_string()),
            };
            row_list.push(format!(
                "<tr><td>{}</td><td>{}</td><td>{}</td><td>{lo}–{hi}</td></tr>",
                esc(fam),
                esc(&n),
                esc(&asr)
            ));
        }
    }
    // serde_json Maps iterate sorted, matching Python's sorted(m["per_family"]).
    let rows = row_list.join("\n");

    let html = format!(
        "<!doctype html>\n\
         <html><head><meta charset=\"utf-8\"><title>peira report — {}</title></head>\n\
         <body>\n\
         <h1>peira report</h1>\n\
         <p>Adapter: {} · Suite: {} ·\n\
         Dataset: {} · peira {}</p>\n\
         <ul>\n\
         <li>ASR (conditional): {} (95% CI {asr_lo}–{asr_hi})</li>\n\
         <li>Benign accuracy: {} (95% CI {acc_lo}–{acc_hi})</li>\n\
         <li>Malformed rate: {}</li>\n\
         <li>Ranking eligible: {}</li>\n\
         </ul>\n\
         <h2>Per-family ASR</h2>\n\
         <table border=\"1\"><tr><th>family</th><th>n</th><th>ASR</th><th>95% CI</th></tr>\n\
         {rows}</table>\n\
         <hr>\n\
         <p><em>A peira score measures robustness on this benchmark's paired\n\
         decision cases. It does not certify a model as safe.</em></p>\n\
         <p>Analysis lock: <code>{}</code></p>\n\
         </body></html>",
        esc(&artifact.adapter_name),
        esc(&artifact.adapter_name),
        esc(&artifact.suite),
        esc(&artifact.dataset_version),
        esc(&artifact.peira_version),
        esc(&mv("asr_conditional")),
        esc(&mv("benign_accuracy")),
        esc(&mv("malformed_rate")),
        esc(&mv("ranking_eligible")),
        esc(&artifact.analysis_lock),
    );
    match fs::write(out, html) {
        Ok(()) => {
            println!("report: {}", out.display());
            EXIT_OK
        }
        Err(e) => {
            eprintln!("error: cannot write {}: {e}", out.display());
            EXIT_INFRA_ERROR
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn cmd_run(
    adapter_arg: &str,
    adapter_version_arg: Option<&str>,
    suite_arg: &str,
    out: &Path,
    dry_run: bool,
    json_progress: bool,
    resume: bool,
) -> u8 {
    let (mut adapter, adapter_name, adapter_version) =
        match resolve_adapter(adapter_arg, adapter_version_arg) {
            Ok(a) => a,
            Err(e) => {
                eprintln!("error: {e}");
                return EXIT_USER_ERROR;
            }
        };

    let suite = if suite_arg == "smoke" {
        "trial"
    } else {
        suite_arg
    };
    let dir = match runner::suite_dir(suite) {
        Some(d) => d,
        None => {
            eprintln!("error: unknown suite '{suite_arg}' (available: trial-demo, trial/smoke)");
            return EXIT_USER_ERROR;
        }
    };
    let suite_path = Path::new(dir);
    if !suite_path.exists() {
        eprintln!(
            "error: suite directory {} not found (the real Trial suite lands with dataset v1; \
             use --suite trial-demo for now)",
            suite_path.display()
        );
        return EXIT_USER_ERROR;
    }

    let cases = match runner::load_cases(suite_path) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("error: invalid case data: {e}");
            return EXIT_USER_ERROR;
        }
    };
    if cases.is_empty() {
        eprintln!("error: no cases found in {}", suite_path.display());
        return EXIT_USER_ERROR;
    }

    if let Err(e) = fs::create_dir_all(out) {
        eprintln!("error: cannot create {}: {e}", out.display());
        return EXIT_INFRA_ERROR;
    }

    if dry_run {
        println!(
            "dry run: {} cases, adapter={adapter_name}, suite={suite_arg} — config valid, nothing scored.",
            cases.len()
        );
        return EXIT_OK;
    }

    // Sanitize path separators out of the artifact filename.
    let safe_adapter: String = adapter_arg
        .chars()
        .map(|c| if c == '/' || c == '\\' { '_' } else { c })
        .collect();
    let partial_path = out.join(format!("{safe_adapter}-{suite}.partial.json"));

    let mut already_done: HashSet<String> = HashSet::new();
    let mut prior_results: Vec<PerCaseResult> = Vec::new();
    if resume && partial_path.exists() {
        match fs::read_to_string(&partial_path) {
            Ok(text) => match RunArtifact::from_json(&text) {
                Ok(partial) => {
                    // P0-2: never trust an unverified partial. The analysis
                    // lock must be intact and the partial must belong to this
                    // exact run — otherwise forged results could be laundered
                    // into a sealed artifact via --resume.
                    if !partial.verify() {
                        eprintln!(
                            "error: partial run {} failed analysis-lock verification — \
                             it was modified or corrupted; delete it or re-run without --resume.",
                            partial_path.display()
                        );
                        return EXIT_USER_ERROR;
                    }
                    if partial.adapter_name != adapter_name
                        || partial.adapter_version != adapter_version
                        || partial.suite != suite
                        || partial.dataset_version != "0.1.0-demo"
                    {
                        eprintln!(
                            "error: partial run {} belongs to a different run \
                             (adapter='{}', version='{}', suite='{}', dataset='{}'); refusing to resume.",
                            partial_path.display(),
                            partial.adapter_name,
                            partial.adapter_version,
                            partial.suite,
                            partial.dataset_version
                        );
                        return EXIT_USER_ERROR;
                    }
                    let case_ids: HashSet<&str> =
                        cases.iter().map(|c| c.case_id.as_str()).collect();
                    let mut ok = true;
                    let mut foreign = 0usize;
                    let mut duplicates = 0usize;
                    for rv in &partial.results {
                        match rv.as_object() {
                            Some(m) => match PerCaseResult::from_json_map(m) {
                                Ok(r) => {
                                    if !case_ids.contains(r.case_id.as_str()) {
                                        foreign += 1;
                                    } else if !already_done.insert(r.case_id.clone()) {
                                        // insert() returns false when the ID was
                                        // already present: a duplicate entry.
                                        duplicates += 1;
                                    } else {
                                        prior_results.push(r);
                                    }
                                }
                                Err(e) => {
                                    ok = false;
                                    eprintln!("warning: could not read partial run ({e}); starting fresh.");
                                    break;
                                }
                            },
                            None => {
                                ok = false;
                                eprintln!(
                                    "warning: could not read partial run (bad result shape); starting fresh."
                                );
                                break;
                            }
                        }
                    }
                    if ok {
                        if foreign > 0 {
                            eprintln!(
                                "warning: ignoring {foreign} foreign case ID(s) in partial run (not in suite {suite})."
                            );
                        }
                        if duplicates > 0 {
                            eprintln!(
                                "warning: ignoring {duplicates} duplicate case ID(s) in partial run."
                            );
                        }
                        println!(
                            "resuming: {} cases already done, {} remaining.",
                            already_done.len(),
                            cases.len().saturating_sub(already_done.len())
                        );
                    } else {
                        already_done.clear();
                        prior_results.clear();
                    }
                }
                Err(e) => {
                    eprintln!("warning: could not read partial run ({e}); starting fresh.");
                }
            },
            Err(e) => {
                eprintln!("warning: could not read partial run ({e}); starting fresh.");
            }
        }
    }

    let progress: Box<dyn Fn(usize, usize)> = if json_progress {
        // Match Python's json.dumps insertion order and separators exactly:
        // {"event": "progress", "done": 1, "total": 12}
        Box::new(|i, total| {
            println!("{{\"event\": \"progress\", \"done\": {i}, \"total\": {total}}}");
        })
    } else {
        Box::new(|i, total| {
            if i == 1 || i == total || i % 50 == 0 {
                eprintln!("  [{i}/{total}]");
            }
        })
    };

    let opts = RunOptions {
        partial_path: Some(&partial_path),
        progress: Some(progress),
        ..Default::default()
    };
    let artifact = runner::run_suite(
        adapter.as_mut(),
        &adapter_name,
        &adapter_version,
        &cases,
        suite,
        "0.1.0-demo",
        &already_done,
        prior_results,
        &opts,
    );

    let out_path = out.join(format!("{safe_adapter}-{suite}.json"));
    let text = match artifact.to_json() {
        Ok(t) => t,
        Err(e) => {
            eprintln!("error: cannot serialize artifact: {e}");
            return EXIT_INFRA_ERROR;
        }
    };
    if let Err(e) = fs::write(&out_path, text) {
        eprintln!("error: cannot write {}: {e}", out_path.display());
        return EXIT_INFRA_ERROR;
    }
    let _ = fs::remove_file(&partial_path);

    let m = &artifact.metrics;
    let mv = |k: &str| m.get(k).map(fmt_val).unwrap_or_default();
    println!("done: {} cases", mv("n_cases"));
    println!(
        "  ASR (conditional): {} 95% CI {}",
        mv("asr_conditional"),
        mv("asr_ci95")
    );
    println!(
        "  benign accuracy:   {} 95% CI {}",
        mv("benign_accuracy"),
        mv("benign_accuracy_ci95")
    );
    println!("  malformed rate:    {}", mv("malformed_rate"));
    let notes: Vec<String> = m
        .get("eligibility_notes")
        .and_then(|v| v.as_array())
        .map(|a| {
            a.iter()
                .filter_map(|v| v.as_str().map(|s| s.to_string()))
                .collect()
        })
        .unwrap_or_default();
    if notes.is_empty() {
        println!("  ranking eligible:  {}", mv("ranking_eligible"));
    } else {
        println!(
            "  ranking eligible:  {} ({})",
            mv("ranking_eligible"),
            notes.join("; ")
        );
    }
    println!("artifact: {}", out_path.display());
    println!("analysis lock: {}…", lock16(&artifact.analysis_lock));
    if m.get("ranking_eligible")
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
    {
        EXIT_OK
    } else {
        EXIT_GATE_NOTE
    }
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    let code = match cli.command {
        Commands::Run {
            adapter,
            adapter_version,
            suite,
            out,
            dry_run,
            json_progress,
            resume,
        } => cmd_run(
            &adapter,
            adapter_version.as_deref(),
            &suite,
            &out,
            dry_run,
            json_progress,
            resume,
        ),
        Commands::Validate { dataset } => cmd_validate(&dataset),
        Commands::Report { run, out } => cmd_report(&run, &out),
        Commands::Verify { run } => cmd_verify(&run),
    };
    ExitCode::from(code)
}
