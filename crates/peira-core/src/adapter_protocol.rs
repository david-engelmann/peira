//! Language-agnostic adapter protocol: run any adapter as a subprocess.
//!
//! The runner spawns the adapter command and speaks JSON lines:
//!
//! - Runner → adapter (stdin), one line per case:
//!   `{"case": {...}, "primitive": "choice"}`
//! - Adapter → runner (stdout), one line per request:
//!   - choice: `{"decision": "approve", "confidence": 0.95}`
//!   - score:  `{"score": 0.7, "decision": "approve"}`
//!   - noul:   `{"decision": "option_a", "abstained": false}`
//!
//! Any language can implement an adapter — no per-language SDK maintenance.
//! The Python PyO3 bindings (`python.rs`) remain for native-speed Python
//! adapters; this module is for everyone else.
//!
//! Error policy: malformed JSON → [`AdapterOutcome::Malformed`], no response
//! within the timeout → [`AdapterOutcome::Timeout`] (the child is killed;
//! the protocol is out of sync afterwards), crash/EOF →
//! [`AdapterOutcome::Crashed`].

use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::Duration;

use serde::{Deserialize, Serialize};

/// One request: the case JSON plus which primitive to decide with.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AdapterRequest {
    pub case: serde_json::Value,
    pub primitive: String,
}

/// Adapter response. Fields are per-primitive (choice: `decision` +
/// `confidence`; score: `score` + `decision`; noul: `decision` +
/// `abstained`); absent fields are `None`. Checking the response against
/// the primitive contract (ranges, required fields) is the caller's job —
/// this module only guarantees it was well-formed JSON.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct AdapterResponse {
    #[serde(default)]
    pub decision: Option<String>,
    #[serde(default)]
    pub confidence: Option<f64>,
    #[serde(default)]
    pub score: Option<f64>,
    #[serde(default)]
    pub abstained: Option<bool>,
}

/// Outcome of one [`SubprocessAdapter::decide`] call.
#[derive(Debug)]
pub enum AdapterOutcome {
    /// The adapter answered with well-formed JSON.
    Ok(AdapterResponse),
    /// The adapter wrote a line that is not valid JSON.
    Malformed(String),
    /// No response line within the timeout. The child is killed and the
    /// adapter is unusable afterwards (a late response would corrupt the
    /// request/response pairing).
    Timeout,
    /// The adapter exited, closed its pipes, or I/O failed.
    Crashed(String),
}

/// An adapter running as a child process, spoken to over JSON lines.
pub struct SubprocessAdapter {
    child: Child,
    stdin: ChildStdin,
    stdout: Option<BufReader<std::process::ChildStdout>>,
    timeout: Duration,
    dead: bool,
}

impl SubprocessAdapter {
    /// Spawn `program` with `args`, speaking JSON lines on its stdio.
    /// `timeout` bounds how long one [`SubprocessAdapter::decide`] waits
    /// for a response line.
    pub fn spawn(program: &str, args: &[&str], timeout: Duration) -> std::io::Result<Self> {
        let mut child = Command::new(program)
            .args(args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()?;
        let stdin = child.stdin.take().expect("stdin was piped");
        let stdout = child
            .stdout
            .take()
            .map(BufReader::new)
            .expect("stdout was piped");
        Ok(Self {
            child,
            stdin,
            stdout: Some(stdout),
            timeout,
            dead: false,
        })
    }

    /// Send one request, read one response line.
    pub fn decide(&mut self, req: &AdapterRequest) -> AdapterOutcome {
        if self.dead {
            return AdapterOutcome::Crashed("adapter already dead".into());
        }
        let mut line = serde_json::to_string(req).expect("request serializes");
        line.push('\n');
        if let Err(e) = self
            .stdin
            .write_all(line.as_bytes())
            .and_then(|()| self.stdin.flush())
        {
            return self.kill(format!("stdin write failed: {e}"));
        }
        // Read one line on a helper thread so the wait is bounded by
        // `timeout`. The BufReader travels into the thread and back through
        // the channel (except on timeout, where the adapter is dead anyway).
        let reader = self.stdout.take().expect("stdout present");
        let timeout = self.timeout;
        let (tx, rx) = mpsc::channel();
        thread::spawn(move || {
            let mut reader = reader;
            let mut line = String::new();
            let res = reader.read_line(&mut line);
            let _ = tx.send((res, line, reader));
        });
        match rx.recv_timeout(timeout) {
            Ok((Ok(0), _, reader)) => {
                self.stdout = Some(reader);
                self.kill("adapter closed stdout (EOF)".into())
            }
            Ok((Ok(_), line, reader)) => {
                self.stdout = Some(reader);
                match serde_json::from_str::<AdapterResponse>(&line) {
                    Ok(resp) => AdapterOutcome::Ok(resp),
                    Err(e) => AdapterOutcome::Malformed(format!("bad JSON: {e}")),
                }
            }
            Ok((Err(e), _, reader)) => {
                self.stdout = Some(reader);
                self.kill(format!("stdout read failed: {e}"))
            }
            Err(mpsc::RecvTimeoutError::Timeout) => {
                // The reader thread stays blocked until the child dies;
                // kill() closes its stdout, which unblocks and ends it.
                self.kill("response timeout".into());
                AdapterOutcome::Timeout
            }
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                self.kill("response reader thread died".into())
            }
        }
    }

    fn kill(&mut self, msg: String) -> AdapterOutcome {
        self.dead = true;
        let _ = self.child.kill();
        AdapterOutcome::Crashed(msg)
    }
}

impl Drop for SubprocessAdapter {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn spawn_sh(script: &str, timeout: Duration) -> SubprocessAdapter {
        SubprocessAdapter::spawn("sh", &["-c", script], timeout).expect("sh should spawn")
    }

    fn req() -> AdapterRequest {
        AdapterRequest {
            case: json!({"id": "v1-demo-001", "prompt": "hello"}),
            primitive: "choice".into(),
        }
    }

    #[test]
    fn request_serializes_to_one_json_line() {
        let s = serde_json::to_string(&req()).unwrap();
        assert!(s.contains("\"primitive\":\"choice\""));
        assert!(!s.contains('\n'));
    }

    #[test]
    fn happy_path_choice() {
        let mut a = spawn_sh(
            r#"while IFS= read -r l; do echo '{"decision":"approve","confidence":0.95}'; done"#,
            Duration::from_secs(5),
        );
        for _ in 0..3 {
            match a.decide(&req()) {
                AdapterOutcome::Ok(r) => {
                    assert_eq!(r.decision.as_deref(), Some("approve"));
                    assert_eq!(r.confidence, Some(0.95));
                }
                o => panic!("expected Ok, got {o:?}"),
            }
        }
    }

    #[test]
    fn score_and_noul_shapes_parse() {
        let mut a = spawn_sh(
            r#"while IFS= read -r l; do echo '{"score":0.7,"decision":"approve"}'; done"#,
            Duration::from_secs(5),
        );
        match a.decide(&req()) {
            AdapterOutcome::Ok(r) => assert_eq!(r.score, Some(0.7)),
            o => panic!("expected Ok, got {o:?}"),
        }
        let mut b = spawn_sh(
            r#"while IFS= read -r l; do echo '{"decision":"option_a","abstained":false}'; done"#,
            Duration::from_secs(5),
        );
        match b.decide(&req()) {
            AdapterOutcome::Ok(r) => {
                assert_eq!(r.decision.as_deref(), Some("option_a"));
                assert_eq!(r.abstained, Some(false));
            }
            o => panic!("expected Ok, got {o:?}"),
        }
    }

    #[test]
    fn malformed_json_marked() {
        let mut a = spawn_sh(
            r#"while IFS= read -r l; do echo 'this is not json'; done"#,
            Duration::from_secs(5),
        );
        assert!(matches!(a.decide(&req()), AdapterOutcome::Malformed(_)));
    }

    #[test]
    fn crash_marked() {
        let mut a = spawn_sh("exit 1", Duration::from_secs(5));
        assert!(matches!(a.decide(&req()), AdapterOutcome::Crashed(_)));
    }

    #[test]
    fn timeout_kills_adapter() {
        let mut a = spawn_sh("while true; do sleep 1; done", Duration::from_millis(200));
        assert!(matches!(a.decide(&req()), AdapterOutcome::Timeout));
        // Out of sync now: further calls report Crashed, not Timeout.
        assert!(matches!(a.decide(&req()), AdapterOutcome::Crashed(_)));
    }
}
