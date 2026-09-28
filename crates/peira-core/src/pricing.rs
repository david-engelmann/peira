//! Pinned model pricing for cost accounting.
//!
//! Mirrors `python/peira/pricing.py::cost_usd`. Cost is a measurement
//! sidecar, never a blended score: the runner fills `cost_usd` on every
//! call record from the pinned table so per-run cost figures are
//! reproducible and traceable.
//!
//! The table itself is package data loaded by the Python side (I/O);
//! this module takes the already-loaded table as a [`serde_json::Value`]
//! and is pure computation from there.

use serde_json::Value;

/// List-price cost of one call in USD.
///
/// Mirrors `pricing.cost_usd(model, tokens_in, tokens_out, table)`:
/// unknown models cost 0.0 (explicitly unaccounted, never silently
/// estimated); negative token counts are a caller bug and raise.
///
/// `table` is the parsed pricing table (`{"models": {model: {"usd_per_1m_in",
/// "usd_per_1m_out"}}}`); a missing `models` section or rate entry is a
/// corrupt table and raises, matching the Python `KeyError`.
pub fn cost_usd(
    model: &str,
    tokens_in: i64,
    tokens_out: i64,
    table: &Value,
) -> Result<f64, String> {
    if tokens_in < 0 || tokens_out < 0 {
        return Err(format!(
            "token counts must be non-negative, got in={tokens_in} out={tokens_out}"
        ));
    }
    let models = table
        .get("models")
        .and_then(|v| v.as_object())
        .ok_or_else(|| "pricing table has no 'models' object".to_string())?;
    let entry = match models.get(model) {
        None => return Ok(0.0),
        Some(e) => e,
    };
    let rate = |key: &str| {
        entry
            .get(key)
            .and_then(|v| v.as_f64())
            .ok_or_else(|| format!("pricing entry for {model:?} has no numeric {key:?}"))
    };
    let per_1m_in = rate("usd_per_1m_in")?;
    let per_1m_out = rate("usd_per_1m_out")?;
    Ok(tokens_in as f64 / 1_000_000.0 * per_1m_in + tokens_out as f64 / 1_000_000.0 * per_1m_out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn table() -> Value {
        json!({
            "models": {
                "m-cheap": {"usd_per_1m_in": 0.1, "usd_per_1m_out": 0.5},
                "m-free": {"usd_per_1m_in": 0.0, "usd_per_1m_out": 0.0},
            }
        })
    }

    #[test]
    fn known_cost() {
        // 1M in @ $0.10 + 2M out @ $0.50 = $1.10
        let c = cost_usd("m-cheap", 1_000_000, 2_000_000, &table()).unwrap();
        assert!((c - 1.10).abs() < 1e-12, "{c}");
    }

    #[test]
    fn unknown_model_costs_zero() {
        assert_eq!(cost_usd("m-nope", 100, 100, &table()).unwrap(), 0.0);
    }

    #[test]
    fn free_model_costs_zero() {
        assert_eq!(cost_usd("m-free", 999_999, 999_999, &table()).unwrap(), 0.0);
    }

    #[test]
    fn negative_tokens_raise() {
        assert!(cost_usd("m-cheap", -1, 0, &table()).is_err());
        assert!(cost_usd("m-cheap", 0, -1, &table()).is_err());
    }

    #[test]
    fn corrupt_table_raises() {
        assert!(cost_usd("m-cheap", 1, 1, &json!({})).is_err());
        assert!(cost_usd("m-cheap", 1, 1, &json!({"models": {"m-cheap": {}}})).is_err());
    }

    #[test]
    fn zero_tokens_zero_cost() {
        assert_eq!(cost_usd("m-cheap", 0, 0, &table()).unwrap(), 0.0);
    }
}
