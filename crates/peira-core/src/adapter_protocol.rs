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
//! Hardening (the adapter is untrusted code):
//!
//! - **Timeout covers the whole exchange.** The request write and the
//!   response read both run on a helper thread bounded by one
//!   `recv_timeout`; a child that never reads stdin cannot wedge
//!   `decide()` before the timeout starts.
//! - **Reads are bounded.** One response line is capped at
//!   [`MAX_LINE_BYTES`] and the adapter's lifetime output at
//!   [`MAX_TOTAL_BYTES`]; exceeding either kills the adapter and yields
//!   [`AdapterOutcome::Oversize`]. A 1 GiB line without a newline can no
//!   longer OOM the runner.
//! - **Process-group kill.** On Unix the child spawns in its own process
//!   group (`setpgid`), and every kill path uses `killpg(SIGKILL)` so
//!   grandchildren die too — `Child::kill` alone would orphan them.
//!
//! Error policy: malformed JSON → [`AdapterOutcome::Malformed`], oversize
//! output → [`AdapterOutcome::Oversize`], no response within the timeout →
//! [`AdapterOutcome::Timeout`] (the whole group is killed; the protocol is
//! out of sync afterwards), crash/EOF → [`AdapterOutcome::Crashed`].
//! Oversize and timeout are fatal to the adapter: later `decide()` calls
//! report [`AdapterOutcome::Crashed`]("adapter already dead").
//!
//! There is no separate handshake: the first `decide()` is the handshake,
//! bounded end-to-end by the timeout.

use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::Duration;

use serde::{Deserialize, Serialize};

/// Cap on a single response line from the adapter (10 MiB). Anything
/// larger is never a legitimate protocol message — kill the adapter.
pub const MAX_LINE_BYTES: u64 = 10 * 1024 * 1024;

/// Cap on total bytes read from one adapter over its lifetime (100 MiB).
/// Bounds slow-drip abuse (many just-under-the-line-cap lines).
pub const MAX_TOTAL_BYTES: u64 = 100 * 1024 * 1024;

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
    /// The adapter's output exceeded [`MAX_LINE_BYTES`] (one line) or
    /// [`MAX_TOTAL_BYTES`] (lifetime). The adapter is killed and unusable
    /// afterwards.
    Oversize(String),
    /// No response line within the timeout. The process group is killed
    /// and the adapter is unusable afterwards (a late response would
    /// corrupt the request/response pairing).
    Timeout,
    /// The adapter exited, closed its pipes, or I/O failed.
    Crashed(String),
}

/// Result of one bounded line read.
enum LineRead {
    /// A full line, newline included (may be empty before the newline).
    Line(Vec<u8>),
    /// EOF before any bytes.
    Eof,
    /// The line exceeded the byte cap (stream is mid-line; caller kills).
    TooLong,
}

/// Read one `\n`-terminated line without letting the buffer grow past
/// `max_bytes`. Uses `fill_buf`/`consume` so at most one extra chunk sits
/// past the cap — a newline-free gigabyte from the adapter cannot OOM us.
fn read_line_capped(
    reader: &mut BufReader<std::process::ChildStdout>,
    max_bytes: u64,
) -> std::io::Result<LineRead> {
    let mut line: Vec<u8> = Vec::new();
    loop {
        let buf = reader.fill_buf()?;
        if buf.is_empty() {
            return Ok(if line.is_empty() {
                LineRead::Eof
            } else {
                // EOF mid-line: hand back what we have; the JSON parse
                // will reject it as malformed if it isn't valid.
                LineRead::Line(line)
            });
        }
        match buf.iter().position(|&b| b == b'\n') {
            Some(pos) => {
                let take = pos + 1; // include the newline
                if line.len() as u64 + take as u64 > max_bytes {
                    return Ok(LineRead::TooLong);
                }
                line.extend_from_slice(&buf[..take]);
                reader.consume(take);
                return Ok(LineRead::Line(line));
            }
            None => {
                if line.len() as u64 + buf.len() as u64 > max_bytes {
                    return Ok(LineRead::TooLong);
                }
                let n = buf.len();
                line.extend_from_slice(buf);
                reader.consume(n);
            }
        }
    }
}

/// An adapter running as a child process, spoken to over JSON lines.
pub struct SubprocessAdapter {
    child: Child,
    stdin: Option<ChildStdin>,
    stdout: Option<BufReader<std::process::ChildStdout>>,
    timeout: Duration,
    dead: bool,
    /// Bytes read from the child so far, for the [`MAX_TOTAL_BYTES`] cap.
    bytes_read: u64,
    /// Process group id (== child pid on Unix). `None` off Unix, where we
    /// fall back to killing just the direct child.
    pgid: Option<i32>,
    max_line_bytes: u64,
    max_total_bytes: u64,
}

impl SubprocessAdapter {
    /// Spawn `program` with `args`, speaking JSON lines on its stdio.
    /// `timeout` bounds one [`SubprocessAdapter::decide`] end-to-end
    /// (request write + response read).
    ///
    /// On Unix the child is placed in its own process group so timeouts
    /// and errors kill grandchildren as well as the direct child.
    pub fn spawn(program: &str, args: &[&str], timeout: Duration) -> std::io::Result<Self> {
        let mut cmd = Command::new(program);
        cmd.args(args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            // SAFETY: setpgid is async-signal-safe; the closure runs
            // between fork and exec with no locks held.
            unsafe {
                cmd.pre_exec(|| {
                    if libc::setpgid(0, 0) != 0 {
                        return Err(std::io::Error::last_os_error());
                    }
                    Ok(())
                });
            }
        }
        let mut child = cmd.spawn()?;
        let pgid = {
            #[cfg(unix)]
            {
                Some(child.id() as i32)
            }
            #[cfg(not(unix))]
            {
                None
            }
        };
        let stdin = child.stdin.take().expect("stdin was piped");
        let stdout = child
            .stdout
            .take()
            .map(BufReader::new)
            .expect("stdout was piped");
        Ok(Self {
            child,
            stdin: Some(stdin),
            stdout: Some(stdout),
            timeout,
            dead: false,
            bytes_read: 0,
            pgid,
            max_line_bytes: MAX_LINE_BYTES,
            max_total_bytes: MAX_TOTAL_BYTES,
        })
    }

    /// Send one request, read one response line. The write and the read
    /// both happen on a helper thread joined with `timeout`, so a child
    /// that never reads stdin (full pipe → blocked write) can no longer
    /// deadlock `decide()` before the timeout begins.
    pub fn decide(&mut self, req: &AdapterRequest) -> AdapterOutcome {
        if self.dead {
            return AdapterOutcome::Crashed("adapter already dead".into());
        }
        let mut line = serde_json::to_string(req).expect("request serializes");
        line.push('\n');
        let request_bytes = line.into_bytes();
        let max_line_bytes = self.max_line_bytes;
        let timeout = self.timeout;
        let mut stdin = self.stdin.take().expect("stdin present");
        let mut reader = self.stdout.take().expect("stdout present");
        let (tx, rx) = mpsc::channel();
        thread::spawn(move || {
            let res: std::io::Result<(ChildStdin, BufReader<std::process::ChildStdout>, LineRead)> =
                (|| {
                    stdin.write_all(&request_bytes)?;
                    stdin.flush()?;
                    let line = read_line_capped(&mut reader, max_line_bytes)?;
                    Ok((stdin, reader, line))
                })();
            let _ = tx.send(res);
        });
        match rx.recv_timeout(timeout) {
            Ok(Ok((stdin_back, reader_back, LineRead::Line(raw)))) => {
                self.stdin = Some(stdin_back);
                self.stdout = Some(reader_back);
                self.bytes_read += raw.len() as u64;
                if self.bytes_read > self.max_total_bytes {
                    self.terminate();
                    return AdapterOutcome::Oversize(format!(
                        "adapter lifetime output exceeded {} bytes",
                        self.max_total_bytes
                    ));
                }
                // Strip one trailing \n and an optional \r (tolerant of
                // CRLF adapters).
                let mut raw = raw;
                if raw.last() == Some(&b'\n') {
                    raw.pop();
                }
                if raw.last() == Some(&b'\r') {
                    raw.pop();
                }
                match String::from_utf8(raw) {
                    Ok(text) => match serde_json::from_str::<AdapterResponse>(&text) {
                        Ok(resp) => AdapterOutcome::Ok(resp),
                        Err(e) => AdapterOutcome::Malformed(format!("bad JSON: {e}")),
                    },
                    Err(_) => AdapterOutcome::Malformed("response is not valid UTF-8".into()),
                }
            }
            Ok(Ok((_, _, LineRead::Eof))) => {
                self.terminate();
                AdapterOutcome::Crashed("adapter closed stdout (EOF)".into())
            }
            Ok(Ok((_, _, LineRead::TooLong))) => {
                // Stream is mid-line; the adapter is out of sync and
                // hostile or broken. Kill it rather than resyncing.
                self.terminate();
                AdapterOutcome::Oversize(format!(
                    "adapter response line exceeded {max_line_bytes} bytes"
                ))
            }
            Ok(Err(e)) => {
                self.terminate();
                AdapterOutcome::Crashed(format!("adapter I/O failed: {e}"))
            }
            Err(mpsc::RecvTimeoutError::Timeout) => {
                // stdin/stdout stay with the helper thread; terminate()
                // kills the group, whose pipe ends close, unblocking the
                // thread so it can exit on its own.
                self.terminate();
                AdapterOutcome::Timeout
            }
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                self.terminate();
                AdapterOutcome::Crashed("response reader thread died".into())
            }
        }
    }

    /// Kill the child and, on Unix, its whole process group; reap it.
    /// Idempotent — the kill only happens once, so a stale pgid can never
    /// be signalled twice (pid reuse hazard).
    fn terminate(&mut self) {
        if self.dead {
            return;
        }
        self.dead = true;
        self.stdin = None;
        self.stdout = None;
        #[cfg(unix)]
        if let Some(pgid) = self.pgid {
            // Kill grandchildren too. ESRCH (already gone) is fine.
            unsafe {
                libc::killpg(pgid, libc::SIGKILL);
            }
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

impl Drop for SubprocessAdapter {
    fn drop(&mut self) {
        self.terminate();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::time::Instant;

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

    #[test]
    fn timeout_when_child_never_reads_stdin() {
        // The old code blocked in stdin write_all() before the timeout
        // machinery started. The child here never reads stdin; the
        // request is small so the write succeeds, but the read must still
        // time out instead of hanging.
        let mut a = spawn_sh("sleep 30", Duration::from_millis(300));
        let start = Instant::now();
        assert!(matches!(a.decide(&req()), AdapterOutcome::Timeout));
        assert!(
            start.elapsed() < Duration::from_secs(10),
            "decide() hung past the timeout"
        );
    }

    #[test]
    fn write_blocks_past_pipe_buffer_still_times_out() {
        // A child that never reads stdin + a request bigger than the pipe
        // buffer (~64 KiB): the old write_all() blocked forever. The
        // write must now be rescued by the timeout.
        let mut a = spawn_sh("sleep 30", Duration::from_millis(500));
        let big = AdapterRequest {
            case: json!({"id": "big", "blob": "y".repeat(1024 * 1024)}),
            primitive: "choice".into(),
        };
        let start = Instant::now();
        assert!(matches!(a.decide(&big), AdapterOutcome::Timeout));
        assert!(
            start.elapsed() < Duration::from_secs(15),
            "write-side deadlock: decide() hung past the timeout"
        );
    }

    #[test]
    fn oversize_line_kills_adapter() {
        // 11 MiB single line: over the 10 MiB cap.
        let mut a = spawn_sh(
            r#"IFS= read -r l; head -c 11534336 /dev/zero | tr '\0' 'x'; echo"#,
            Duration::from_secs(20),
        );
        match a.decide(&req()) {
            AdapterOutcome::Oversize(msg) => assert!(msg.contains("exceeded")),
            o => panic!("expected Oversize, got {o:?}"),
        }
        // Adapter is dead afterwards.
        assert!(matches!(a.decide(&req()), AdapterOutcome::Crashed(_)));
    }

    #[test]
    fn total_output_cap() {
        // Valid JSON lines padded to ~1460 bytes each.
        let mut a = spawn_sh(
            r#"while IFS= read -r l; do printf '{"decision":"approve","confidence":0.5,"pad":"%01400s"}\n' ''; done"#,
            Duration::from_secs(10),
        );
        // Shrink the caps for a fast test (same-module: private fields OK).
        a.max_total_bytes = 2048;
        match a.decide(&req()) {
            AdapterOutcome::Ok(r) => assert_eq!(r.decision.as_deref(), Some("approve")),
            o => panic!("expected Ok, got {o:?}"),
        }
        match a.decide(&req()) {
            AdapterOutcome::Oversize(msg) => assert!(msg.contains("lifetime")),
            o => panic!("expected Oversize, got {o:?}"),
        }
    }

    #[test]
    fn crlf_line_endings_tolerated() {
        let mut a = spawn_sh(
            r#"while IFS= read -r l; do printf '{"decision":"approve","confidence":0.5}\r\n'; done"#,
            Duration::from_secs(5),
        );
        match a.decide(&req()) {
            AdapterOutcome::Ok(r) => assert_eq!(r.decision.as_deref(), Some("approve")),
            o => panic!("expected Ok, got {o:?}"),
        }
    }

    #[cfg(unix)]
    #[test]
    fn timeout_kills_process_group() {
        // The child spawns a grandchild (sleep 300) in the same process
        // group. Old code's Child::kill left the grandchild orphaned;
        // killpg must take the whole group.
        let mut a = spawn_sh("sleep 300 & wait", Duration::from_millis(300));
        let pgid = a.pgid.expect("pgid set on unix");
        assert!(matches!(a.decide(&req()), AdapterOutcome::Timeout));
        // Poll for the group to be gone (kill with sig 0 = existence check).
        let deadline = Instant::now() + Duration::from_secs(5);
        loop {
            let rc = unsafe { libc::kill(pgid, 0) };
            if rc != 0 {
                break; // ESRCH: group is gone
            }
            assert!(Instant::now() < deadline, "process group survived killpg");
            thread::sleep(Duration::from_millis(50));
        }
    }
}
