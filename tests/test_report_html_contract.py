"""Contract tests for self-contained HTML report artifacts (P-13).

The contract: no JavaScript, no external resources, charts as inline
SVG, every interpolated value escaped, data source bannered. These
tests pin the contract so a future edit cannot silently break it.

The page design is the dark dashboard: tiles, a ranking chart, a
family heatmap, a cost scatter, a malformed strip and model cards,
with rates in percent throughout. Assertions that pinned the earlier
editorial layout (decimal rate cells, per-family denominator tables,
the calibration count table) were retired with that layout; the
data-integrity assertions (every model present with full numbers,
reasons shown, hashes printed, copy bar) carry over.

Run with: PYTHONPATH=python python3 -m pytest tests/test_report_html_contract.py
"""

import re
import unittest
from html import unescape

from peira.report_html import leaderboard_to_html


def _payload():
    return {
        "ranked": [
            {
                "adapter_name": "shieldstral-1.0",
                "adapter_version": "1.0",
                "asr_conditional": 0.20,
                "asr_ci95": [0.15, 0.26],
                "benign_accuracy": 0.97,
                "n_eligible": 400,
                "total_cost_usd": 1.23,
                "latency_ms_p50_attacked": 210.5,
                "ece_attacked": 0.04,
            },
            {
                # Hostile name: markup must land inert.
                "adapter_name": "<script>alert('x')</script>",
                "adapter_version": "9.9",
                "asr_conditional": 0.60,
                "asr_ci95": [0.55, 0.65],
                "benign_accuracy": 0.90,
                "n_eligible": 400,
                "total_cost_usd": 0.50,
                "latency_ms_p50_attacked": 100.0,
                "ece_attacked": 0.10,
            },
        ],
        "unranked": [
            {
                "adapter_name": "broken-adapter",
                "adapter_version": "0.1",
                "reason": "benign accuracy below ranking floor",
            }
        ],
    }


def _hero_svg(page):
    start = page.index('class="chart hero-svg"')
    start = page.rindex("<svg", 0, start)
    return page[start:page.index("</svg>", start)]


class ContractTest(unittest.TestCase):
    def test_no_javascript(self):
        page = leaderboard_to_html(_payload())
        self.assertNotIn("<script", page.lower())

    def test_no_external_resources(self):
        page = leaderboard_to_html(_payload())
        self.assertNotIn("<link", page.lower())
        self.assertNotIn("<img", page.lower())
        for m in re.finditer(r'(src|href)\s*=\s*"([^"]*)"', page):
            self.assertFalse(m.group(2).startswith(("http://", "https://", "//")),
                             f"external resource: {m.group(0)}")

    def test_heatmap_renders_mapping_shape(self):
        # The data layer emits per-run families as a mapping keyed by
        # family name. The heatmap must render those rates as cells,
        # mark the retrieval column, and print n/a where a model
        # lacks a family.
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {
                "retrieval_poisoning": {
                    "family": "retrieval_poisoning",
                    "asr": 0.7672,
                    "asr_ci95": [0.726, 0.804],
                    "n": 470,
                },
                "canary_leakage": {
                    "family": "canary_leakage",
                    "asr": 0.05, "asr_ci95": [0.03, 0.08], "n": 470,
                },
            },
            "calibration": {},
        }
        payload["ranked"][1]["detail"] = {
            "families": {
                "retrieval_poisoning": {
                    "family": "retrieval_poisoning",
                    "asr": 0.15, "asr_ci95": [0.11, 0.19], "n": 470,
                },
            },
            "calibration": {},
        }
        page = leaderboard_to_html(payload)
        self.assertIn("Attack family heatmap", page)
        self.assertIn('class="hot-col"', page)
        self.assertIn("RETRIEVAL", page)
        self.assertIn(">77<", page)
        self.assertIn(">5<", page)
        self.assertIn(">15<", page)
        self.assertIn('<td class="na">n/a</td>', page)

    def test_provenance_falls_back_to_row_fields(self):
        # An unfiltered payload carries no suite or dataset version at
        # the top level. The strip and footer must read them from the
        # rows rather than rendering n/a, and the run-date range must
        # cover unranked rows too.
        payload = _payload()
        payload["ranked"][0]["suite"] = "v2"
        payload["ranked"][0]["dataset_version"] = "2.6.0"
        payload["ranked"][0]["created_utc"] = "2026-10-07T15:00:00+00:00"
        payload["unranked"][0]["created_utc"] = "2026-10-12T15:00:00+00:00"
        page = leaderboard_to_html(payload)
        self.assertIn("suite v2", page)
        self.assertIn("dataset 2.6.0", page)
        self.assertIn("runs from 7 to 12 October 2026", page)

    def test_run_window_uses_the_trial_local_frame(self):
        # The page dates events in the trial record's frame,
        # America/New_York. A stamp just after midnight UTC is
        # the previous evening local, and the window must say
        # so, or the footer would date the same event a day
        # later than the re-run disclosure on the same page.
        payload = _payload()
        payload["ranked"][0]["created_utc"] = "2026-10-13T00:07:00+00:00"
        payload["ranked"][1]["created_utc"] = "2026-10-13T00:07:00+00:00"
        page = leaderboard_to_html(payload)
        self.assertIn("runs on 12 October 2026", page)
        self.assertNotIn("13 October 2026", page)

    def test_run_notes_absent_for_unaffected_models(self):
        page = leaderboard_to_html(_payload())
        self.assertNotIn("Run notes", page)
        self.assertNotIn("thinking mode", page)
        self.assertNotIn("re-run under fixed adapters", page)
        self.assertNotIn("single-configuration throughout", page)

    def test_run_notes_disclose_segment_reruns(self):
        payload = _payload()
        payload["ranked"].append({
            "run_id": "moonshot-v2-trial",
            "adapter_name": "moonshot-structured",
            "adapter_version": "kimi-k3",
            "display_name": "kimi-k3",
            "asr_conditional": 0.30,
            "asr_ci95": [0.25, 0.35],
            "benign_accuracy": 0.95,
            "n_eligible": 400,
            "total_cost_usd": 1.00,
            "latency_ms_p50_attacked": 100.0,
            "ece_attacked": 0.05,
        })
        payload["unranked"].append({
            "run_id": "google-v2-trial",
            "adapter_name": "google-structured",
            "adapter_version": "gemini-3.8-flash",
            "display_name": "gemini-3.8-flash",
            "reason": "benign accuracy below ranking floor",
        })
        page = leaderboard_to_html(payload)
        self.assertIn("Run notes.", page)
        # The notes disclose the segment re-runs: both runs, both
        # segment sizes, the date, and the reason, and they state
        # the runs are single-configuration like every other run.
        self.assertIn(
            "The first 1,610 cases of the gemini-3.8-flash run and "
            "the first 3,274 cases of the kimi-k3 run were re-run "
            "under fixed adapters on 12 October 2026", page)
        self.assertIn(
            "adapter defect was found in the original segments", page)
        self.assertIn(
            "Every run on this page is single-configuration "
            "throughout.", page)
        # The cards carry the short form of the same disclosure.
        self.assertIn(
            "First 1,610 cases re-run under the fixed adapter", page)
        self.assertIn(
            "First 3,274 cases re-run under the fixed adapter", page)
        # No name carries a mark, and none of the retired
        # two-configuration claims survives anywhere on the page.
        self.assertNotIn("kimi-k3*", page)
        self.assertNotIn("gemini-3.8-flash*", page)
        self.assertNotIn("thinking mode", page)
        self.assertNotIn("two configurations", page)
        self.assertNotIn("blends both configurations", page)

    def test_rerun_note_keys_on_run_id(self):
        # The disclosure belongs to the run itself, keyed by
        # run_id, never by a display name another run could
        # share. A row presented as kimi-k3 under a different
        # run_id, or with no run_id at all, must not inherit a
        # dated, sized provenance claim, and an adapter_version
        # of an unexpected type must neither fabricate the note
        # nor break the render.
        payload = _payload()
        payload["ranked"].append({
            "run_id": "other-v2-trial",
            "adapter_name": "other-structured",
            "adapter_version": "kimi-k3",
            "display_name": "kimi-k3",
            "asr_conditional": 0.30,
            "asr_ci95": [0.25, 0.35],
            "benign_accuracy": 0.95,
            "n_eligible": 400,
            "total_cost_usd": 1.00,
            "latency_ms_p50_attacked": 100.0,
            "ece_attacked": 0.05,
        })
        payload["ranked"].append({
            "adapter_name": "odd-structured",
            "adapter_version": ["kimi-k3"],
            "display_name": "Odd Version Model",
            "asr_conditional": 0.31,
            "asr_ci95": [0.26, 0.36],
            "benign_accuracy": 0.94,
            "n_eligible": 400,
            "total_cost_usd": 1.00,
            "latency_ms_p50_attacked": 100.0,
            "ece_attacked": 0.05,
        })
        page = leaderboard_to_html(payload)
        self.assertNotIn("re-run under fixed adapters", page)
        self.assertNotIn("re-run under the fixed adapter", page)
        # The genuine run_id carries the disclosure whatever
        # name the row presents under.
        payload2 = _payload()
        payload2["ranked"].append({
            "run_id": "moonshot-v2-trial",
            "adapter_name": "moonshot-structured",
            "adapter_version": "kimi-k3",
            "display_name": "Renamed Presentation",
            "asr_conditional": 0.30,
            "asr_ci95": [0.25, 0.35],
            "benign_accuracy": 0.95,
            "n_eligible": 400,
            "total_cost_usd": 1.00,
            "latency_ms_p50_attacked": 100.0,
            "ece_attacked": 0.05,
        })
        page2 = leaderboard_to_html(payload2)
        self.assertIn(
            "First 3,274 cases re-run under the fixed adapter", page2)
        self.assertIn(
            "The first 3,274 cases of the Renamed Presentation "
            "run were re-run", page2)

    def test_malformed_strip_orders_rate_ties_by_asr(self):
        # Two runs with the same malformed rate print in ASR
        # order in the strip summary, whichever order the payload
        # lists them in, so the tie order is a property of the
        # data and not of the caller's row order.
        payload = _payload()
        payload["ranked"] = [
            {
                "adapter_name": "slow-model",
                "adapter_version": "s1",
                "asr_conditional": 0.30,
                "asr_ci95": [0.25, 0.35],
                "benign_accuracy": 0.95,
                "n_eligible": 400,
                "total_cost_usd": 1.00,
                "latency_ms_p50_attacked": 100.0,
                "ece_attacked": 0.05,
                "malformed_rate": 0.02,
            },
            {
                "adapter_name": "fast-model",
                "adapter_version": "f1",
                "asr_conditional": 0.10,
                "asr_ci95": [0.06, 0.15],
                "benign_accuracy": 0.97,
                "n_eligible": 400,
                "total_cost_usd": 2.00,
                "latency_ms_p50_attacked": 100.0,
                "ece_attacked": 0.04,
                "malformed_rate": 0.02,
            },
        ]
        payload["unranked"] = []
        page = leaderboard_to_html(payload)
        desc_start = page.index('<desc id="malf-d">')
        desc = page[desc_start:page.index("</desc>", desc_start)]
        self.assertLess(desc.index("fast-model"),
                        desc.index("slow-model"))

    def test_single_model_payload_renders_a_complete_page(self):
        payload = _payload()
        payload["ranked"] = payload["ranked"][:1]
        payload["unranked"] = []
        page = leaderboard_to_html(payload)
        self.assertIn("shieldstral-1.0", page)
        self.assertIn("RANK 1 OF 1 RANKED", page)
        self.assertNotIn("TIED", page)
        self.assertIn("</footer>", page)

    def test_charts_are_inline_svg(self):
        page = leaderboard_to_html(_payload())
        self.assertIn("<svg", page)
        # The hero chart draws bars as rects and whiskers as lines.
        svg = _hero_svg(page)
        self.assertIn("<line", svg)
        self.assertIn("<rect", svg)
        # The cost scatter draws its points as circles.
        scatter_start = page.index('id="scatter-t"')
        scatter_start = page.rindex("<svg", 0, scatter_start)
        scatter = page[scatter_start:page.index("</svg>", scatter_start)]
        self.assertIn("<circle", scatter)

    def test_hostile_names_are_escaped(self):
        page = leaderboard_to_html(_payload())
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)

    def test_benchmark_names_are_escaped_in_footer(self):
        # The footer sentence naming the robust-tax benchmarks
        # interpolates model names like every other surface. A
        # slash-free hostile name holding both benchmarks must
        # land inert there too (a name with a slash in it is
        # shortened by the chart name rule and never exercised
        # this path).
        payload = _payload()
        payload["ranked"][0]["display_name"] = "<u>UNDERLINED"
        payload["ranked"][0]["benign_accuracy"] = 0.99
        payload["ranked"][0]["ece_attacked"] = 0.001
        page = leaderboard_to_html(payload)
        self.assertNotIn("<u>UNDERLINED", page)
        self.assertIn(
            "the benchmarks are the best ranked runs, "
            "&lt;u&gt;UNDERLINED at 99.0%",
            page)

    def test_mock_banner_is_default(self):
        page = leaderboard_to_html(_payload())
        self.assertIn("MOCK DATA", page)
        self.assertNotIn("Official results", page)

    def test_official_banner_when_declared(self):
        page = leaderboard_to_html(_payload(), data_source="official")
        self.assertIn("Official results", page)
        self.assertNotIn("MOCK DATA", page)

    def test_unranked_reasons_shown(self):
        page = leaderboard_to_html(_payload())
        self.assertIn("FLAGGED · NO RANK", page)
        self.assertIn("benign accuracy below ranking floor", page)

    def test_unranked_rows_render_full_numbers(self):
        # A not-ranked row whose payload carries stats prints them in
        # the hero chart, the malformed strip, its card and the
        # heatmap, with the flag marker in place of a rank.
        payload = _payload()
        payload["unranked"][0].update({
            "asr_conditional": 0.30,
            "asr_ci95": [0.25, 0.35],
            "benign_accuracy": 0.95,
            "n_eligible": 400,
            "total_cost_usd": 0.75,
            "latency_ms_p50_attacked": 150.0,
            "ece_attacked": 0.07,
            "malformed_rate": 0.11,
            "detail": {
                "families": {
                    "indirection": {
                        "family": "indirection",
                        "asr": 0.31,
                        "asr_ci95": [0.26, 0.36],
                        "n": 400,
                    },
                },
                "calibration": {},
            },
        })
        page = leaderboard_to_html(payload)
        self.assertIn("30.0%", page)
        self.assertIn("11.0%", page)
        self.assertIn("FLAGGED · NO RANK", page)
        self.assertIn("broken-adapter", page)
        self.assertIn(">31<", page)

    def test_hero_prints_values_and_marks_flagged_with_hatch(self):
        # Every hero bar carries its value as a printed label, ranked
        # bars are solid green, and a not-ranked model draws as a
        # hatched bar with its malformed rate beside it.
        payload = _payload()
        payload["unranked"][0].update({
            "asr_conditional": 0.30, "asr_ci95": [0.25, 0.35],
            "n_eligible": 400, "malformed_rate": 0.11,
        })
        page = leaderboard_to_html(payload)
        svg = _hero_svg(page)
        self.assertIn("20.0%", svg)
        self.assertIn("30.0%", svg)
        self.assertIn('fill="#2fbf71"', svg)
        self.assertIn('fill="url(#hatch)"', svg)
        self.assertIn("malformed 11.0%", svg)

    def test_malformed_strip_draws_admission_line(self):
        # The malformed strip sorts worst first, turns bars past
        # the gate amber (the flag colour), keeps bars under it
        # green, and draws the 5 percent admission line dashed
        # and labelled.
        payload = _payload()
        payload["ranked"][0]["malformed_rate"] = 0.04
        payload["unranked"][0].update({
            "asr_conditional": 0.30, "asr_ci95": [0.25, 0.35],
            "malformed_rate": 0.11,
        })
        page = leaderboard_to_html(payload)
        self.assertIn("Malformed response rate", page)
        self.assertIn("5% admission line", page)
        self.assertIn('fill="#e8a33d"', page)
        # One ranked green page-wide (pass 16): the strip's
        # under-line bars carry the same #2fbf71 as the hero
        # bars and scatter discs, not a darker second green.
        self.assertIn('fill="#2fbf71"', page)
        self.assertIn("11.0%", page)
        self.assertIn("4.0%", page)

    def test_mobile_ranking_lists_every_model(self):
        # Small screens get a native ranking list, not the desktop
        # chart shrunk. Every model appears with its rate and
        # interval in plain markup, and CSS swaps the two forms.
        payload = _payload()
        payload["unranked"][0].update({
            "asr_conditional": 0.30, "asr_ci95": [0.25, 0.35],
            "n_eligible": 400, "malformed_rate": 0.11,
        })
        page = leaderboard_to_html(payload)
        self.assertIn('<div class="hero-mobile">', page)
        mobile = page[page.index('<div class="hero-mobile">'):]
        self.assertIn("20.0%", mobile)
        self.assertIn("30.0%", mobile)
        self.assertIn("95% CI 25.0% to 35.0%", mobile)
        self.assertIn("FLAGGED", mobile)
        self.assertIn(".hero-svg{display:none}", page)
        self.assertIn(".hero-mobile{display:block}", page)

    def test_card_surfaces_severity_p95_and_tax(self):
        # The payload carries severity breakdowns, latency p95, a
        # robustness tax and calibration Brier. The model card must
        # surface all four rather than leaving them in the JSON.
        payload = _payload()
        payload["ranked"][0].update({
            "latency_ms_p95_attacked": 1849.0361,
            "robustness_tax": 0.0007,
        })
        payload["ranked"][0]["detail"] = {
            "families": {},
            "calibration": {"attacked": {"brier": 0.1302}},
            "severities": {
                "critical": {
                    "flip_rate_raw": 0.0781,
                    "flip_rate_ci95": [0.0633, 0.096],
                    "n_flipped": 81,
                    "n_eligible": 1037,
                },
            },
        }
        page = leaderboard_to_html(payload)
        self.assertIn("SEV FLIP RATE C·H·M", page)
        # Only the critical block exists in this fixture, so the
        # high and medium slots print n/a in place rather than
        # collapsing the triple into a lone value under a C·H·M
        # label.
        self.assertIn(">7.8%·n/a·n/a<", page)
        self.assertIn("CALIB N", page)
        self.assertIn("LATENCY P95", page)
        self.assertIn("1.85s", page)
        self.assertIn("ROBUST TAX", page)
        # The tax is defined in points, so it prints in points,
        # not as a percent of anything.
        self.assertIn("0.1 pts", page)
        self.assertIn("BRIER", page)
        self.assertIn("0.130", page)

    def test_family_rate_prints_from_counts_not_stored_rounding(self):
        # Pass 37: a family rate stored at four decimals is a
        # rounding of the count ratio the same record carries.
        # 14 of 418 is 3.349 percent: the stored 0.0335 formats
        # to 3.4%, but the exact figure prints 3.3% on every
        # surface (heat cell text in both tables, spark title).
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {
                "judge_sycophancy": {
                    "asr": 0.0335,
                    "n_flipped": 14,
                    "n_eligible": 418,
                    "n_costed_calls": 836,
                    "n_latency_calls": 836,
                    "cost_usd": 0.5,
                },
            },
            "calibration": {"attacked": {}},
            "severities": {},
        }
        page = leaderboard_to_html(payload)
        self.assertIn("judge sycophancy 3.3% · n 418", page)
        self.assertNotIn("judge sycophancy 3.4%", page)

    def test_ci_prints_from_counts_not_stored_rounding(self):
        # Pass 37: the stored interval is the Wilson interval
        # over the run's counts at four decimals. 743 of 4,621
        # gives a lower bound of 15.048 percent: the stored
        # 0.1505 formats to 15.1%, but the exact bound prints
        # 15.0% in the hero text and on the card.
        payload = _payload()
        payload["ranked"][0].update({
            "asr_conditional": 0.1608,
            "asr_ci95": [0.1505, 0.1717],
            "n_eligible": 4621,
        })
        payload["ranked"][0]["detail"] = {
            "families": {
                "retrieval_poisoning": {
                    "asr": 0.1608,
                    "n_flipped": 743,
                    "n_eligible": 4621,
                    "n_costed_calls": 9242,
                    "n_latency_calls": 9242,
                    "cost_usd": 0.5,
                },
            },
            "calibration": {"attacked": {}},
            "severities": {},
        }
        page = leaderboard_to_html(payload)
        self.assertIn("95% CI 15.0% to 17.2%", page)
        self.assertNotIn("95% CI 15.1%", page)

    def test_counts_that_disagree_with_stored_rate_do_not_derive(self):
        # Pass 37: the derivation is guarded. Counts encoding a
        # different figure than the stored field (100 of 400
        # against a stored 0.0335) prove nothing about the
        # stored rate, so the stored figure prints as before.
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {
                "judge_sycophancy": {
                    "asr": 0.0335,
                    "n_flipped": 100,
                    "n_eligible": 400,
                    "n_costed_calls": 800,
                    "n_latency_calls": 800,
                    "cost_usd": 0.5,
                },
            },
            "calibration": {"attacked": {}},
            "severities": {},
        }
        page = leaderboard_to_html(payload)
        self.assertIn("judge sycophancy 3.4% · n 400", page)
        self.assertNotIn("judge sycophancy 25.0%", page)

    def test_family_rate_without_counts_prints_stored_field(self):
        # Pass 37: with no counts in the record there is nothing
        # to derive from, and the stored field prints as before.
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {
                "judge_sycophancy": {
                    "asr": 0.0335,
                    "n_eligible": 418,
                },
            },
            "calibration": {"attacked": {}},
            "severities": {},
        }
        page = leaderboard_to_html(payload)
        self.assertIn("judge sycophancy 3.4% · n 418", page)

    def test_provenance_prints_payload_hash(self):
        payload = _payload()
        page = leaderboard_to_html(
            payload, payload_sha256="a" * 64)
        self.assertIn("payload sha256", page)
        self.assertIn("a" * 16, page)
        # Without an explicit hash the footer still prints one, the
        # hash of the canonical payload form.
        page2 = leaderboard_to_html(payload)
        self.assertIn("payload sha256", page2)

    def test_scatter_labels_log_axis(self):
        # The cost scatter is log scale. Its axis must carry power of
        # ten ticks and its caption must say the axis is log, so a
        # point position is never read as a dollar difference.
        payload = _payload()
        payload["ranked"][0].update({"total_cost_usd": 0.20})
        payload["ranked"][1].update({"total_cost_usd": 40.0})
        page = leaderboard_to_html(payload)
        self.assertIn("Log cost axis", page)
        for tick in ("$0.1", "$1", "$10", "$100"):
            self.assertIn(tick, page)
        self.assertIn("$40.00", page)

    def test_kpi_tiles_carry_headline_figures(self):
        # The tiles across the top are computed from the payload:
        # model count, cases per run, lowest ASR and cost spread.
        payload = _payload()
        for row in payload["ranked"] + payload["unranked"]:
            row["n_cases"] = 4701
        page = leaderboard_to_html(payload)
        self.assertIn("MODELS TESTED", page)
        self.assertIn("PAIRED CASES EACH", page)
        self.assertIn("4,701", page)
        self.assertIn("LOWEST ASR", page)
        self.assertNotIn("STRONGEST", page)
        self.assertIn("COST SPREAD PER RUN", page)

    def test_kpi_tile_discloses_a_tied_lead(self):
        # When the top two ranked intervals overlap, the lead tile
        # must say the lead is tied rather than crown a winner.
        payload = _payload()
        payload["ranked"][1]["asr_conditional"] = 0.21
        payload["ranked"][1]["asr_ci95"] = [0.16, 0.27]
        page = leaderboard_to_html(payload)
        self.assertIn("TIED", page)

    def test_all_models_render_with_numbers(self):
        # A twelve model payload renders every model by name with
        # its rate on the page, ranked and flagged alike.
        rows = []
        for i in range(12):
            rows.append({
                "adapter_name": f"model-{i:02d}",
                "adapter_version": f"{i}.0",
                "asr_conditional": 0.10 + i * 0.01,
                "asr_ci95": [0.09 + i * 0.01, 0.11 + i * 0.01],
                "benign_accuracy": 0.97,
                "n_eligible": 400,
                "n_cases": 4701,
                "total_cost_usd": 1.0 + i,
                "latency_ms_p50_attacked": 100.0,
                "ece_attacked": 0.05,
                "malformed_rate": 0.01,
            })
        payload = {"ranked": rows[:6], "unranked": rows[6:]}
        for row in payload["unranked"]:
            row["reason"] = "ranking-ineligible: malformed_rate above 5%"
            row["malformed_rate"] = 0.09
        page = leaderboard_to_html(payload)
        for i, row in enumerate(rows):
            self.assertIn(f"model-{i:02d}", page)
            self.assertIn(f"{row['asr_conditional'] * 100:.1f}%", page)
        self.assertEqual(page.count("FLAGGED · NO RANK"), 6)

    def test_visible_text_respects_copy_bar(self):
        # Public copy carries no em dashes, no colons and no
        # semicolons in prose. Scan the visible text only, with the
        # style block and all markup stripped, using an explicit
        # codepoint check so the scan cannot silently match nothing.
        page = leaderboard_to_html(_payload())
        text = re.sub(r"<style.*?</style>", " ", page, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        # Unescape so entity punctuation in escaped fixture names
        # is not mistaken for prose punctuation.
        text = unescape(text)
        self.assertNotIn("\u2014", text)
        self.assertNotIn(";", text)
        self.assertNotIn(":", text)

    def test_no_winner_claim_copy(self):
        # Nothing on the page crowns a model the intervals cannot
        # separate. The retrieval figures render as heatmap values,
        # never as prose claims about a strongest model.
        payload = _payload()
        for row in payload["ranked"]:
            row["detail"] = {
                "families": {
                    "retrieval_poisoning": {
                        "family": "retrieval_poisoning",
                        "asr": 0.70, "asr_ci95": [0.65, 0.75],
                        "n_eligible": 432,
                    },
                },
                "calibration": {},
            }
        page = leaderboard_to_html(payload)
        self.assertIn(">70<", page)
        self.assertNotIn("lowest recorded", page)
        self.assertNotIn("strongest overall", page)

    def test_ranking_content(self):
        page = leaderboard_to_html(_payload())
        self.assertIn("shieldstral-1.0", page)
        self.assertIn("20.0%", page)
        self.assertIn("95% CI 15.0% to 26.0%", page)

    def test_empty_payload_renders(self):
        page = leaderboard_to_html({"ranked": [], "unranked": []})
        # Chart degrades to a text note, never a broken page.
        self.assertIn("No ranked models with ASR data", page)
        self.assertIn("MOCK DATA", page)

    def test_is_one_file(self):
        page = leaderboard_to_html(_payload())
        self.assertTrue(page.startswith("<!DOCTYPE html>"))
        self.assertTrue(page.rstrip().endswith("</html>"))

    def test_absent_ci_is_never_fabricated(self):
        payload = _payload()
        del payload["ranked"][0]["asr_ci95"]
        page = leaderboard_to_html(payload)
        # No zero-width invented interval anywhere, and the phone
        # list says what the card says.
        self.assertNotIn("95% CI 20.0% to 20.0%", page)
        self.assertIn("no interval recorded", page)

    def test_missing_severity_holds_its_slot(self):
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "severities": {
                "critical": {"flip_rate_raw": 0.10, "n_eligible": 100},
                "medium": {"flip_rate_raw": 0.30, "n_eligible": 300},
            }
        }
        page = leaderboard_to_html(payload)
        # The missing high severity stays visibly missing in the
        # middle slot rather than letting medium shift into it.
        self.assertIn("10.0%·n/a·30.0%", page)
        self.assertIn("100·n/a·300", page)

    def test_wrong_typed_fields_do_not_crash(self):
        payload = _payload()
        payload["ranked"][0]["detail"] = "junk"
        payload["ranked"][0]["created_utc"] = 20261007
        page = leaderboard_to_html(payload)
        self.assertIn("shieldstral-1.0", page)

    def test_print_stylesheet_present(self):
        page = leaderboard_to_html(_payload())
        self.assertIn("@media print", page)
        self.assertIn("print-color-adjust:exact", page)
        self.assertIn("break-inside:avoid", page)

    def test_stored_half_rounds_up(self):
        payload = _payload()
        payload["ranked"][0]["asr_ci95"] = [0.1505, 0.1717]
        page = leaderboard_to_html(payload)
        # Decimal half-up on the stored value, the same rounding
        # a reader recomputing from the payload would apply.
        self.assertIn("95% CI 15.1% to 17.2%", page)

    def test_inverted_interval_is_no_interval(self):
        # An interval whose low end sits above its high end is
        # not an interval. It must render exactly like a missing
        # one, never as a verbatim inverted range.
        payload = _payload()
        payload["ranked"][0]["asr_ci95"] = [0.30, 0.20]
        page = leaderboard_to_html(payload)
        self.assertNotIn("30.0% to 20.0%", page)
        self.assertIn("ASR · no interval recorded", page)

    def test_flagged_row_prints_no_robust_tax(self):
        # The footer scopes the tax to ranked runs. A flagged row
        # carrying the figure anyway must not print it, while a
        # ranked row with the same figure prints it in points.
        payload = _payload()
        payload["ranked"][0]["robustness_tax"] = 0.99
        payload["unranked"][0].update({
            "asr_conditional": 0.30,
            "robustness_tax": 0.88,
        })
        page = leaderboard_to_html(payload)
        self.assertIn("99.0 pts", page)
        self.assertNotIn("88.0 pts", page)

    def test_tied_band_marks_chips_and_caption(self):
        # Ranks 2 and 3 hold intervals that overlap each other
        # while rank 1 stands clear. The band is marked on both
        # cards and in the caption, with the same courtesy the
        # tied lead gets, and rank 1 is marked with nothing.
        payload = _payload()
        payload["ranked"] = [
            {"adapter_name": "alpha", "adapter_version": "1",
             "asr_conditional": 0.10, "asr_ci95": [0.08, 0.12],
             "benign_accuracy": 0.97, "n_eligible": 400,
             "total_cost_usd": 1.0, "ece_attacked": 0.04},
            {"adapter_name": "beta", "adapter_version": "1",
             "asr_conditional": 0.20, "asr_ci95": [0.17, 0.24],
             "benign_accuracy": 0.95, "n_eligible": 400,
             "total_cost_usd": 1.0, "ece_attacked": 0.05},
            {"adapter_name": "gamma", "adapter_version": "1",
             "asr_conditional": 0.23, "asr_ci95": [0.20, 0.27],
             "benign_accuracy": 0.94, "n_eligible": 400,
             "total_cost_usd": 1.0, "ece_attacked": 0.06},
        ]
        payload["unranked"] = []
        page = leaderboard_to_html(payload)
        self.assertIn("RANK 2 OF 3 RANKED · TIED 2–3", page)
        self.assertIn("RANK 3 OF 3 RANKED · TIED 2–3", page)
        self.assertIn("RANK 1 OF 3 RANKED</span>", page)
        self.assertIn("ranks 2 to 3 overlap, a tie", page)

    def test_nav_links_only_emitted_sections(self):
        # The module nav is built from the sections the render
        # actually emits, so an empty payload leaves no dead
        # links to sections that are not on the page.
        page = leaderboard_to_html({})
        self.assertIn('href="#ranking"', page)
        self.assertIn('href="#notes"', page)
        self.assertNotIn('href="#heatmap"', page)
        self.assertNotIn('href="#cost"', page)
        self.assertNotIn('href="#malformed"', page)
        self.assertNotIn('href="#cards"', page)

    def _families_payload(self):
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {
                "canary_leakage": {
                    "family": "canary_leakage",
                    "asr": 0.05, "asr_ci95": [0.03, 0.08], "n": 470,
                },
                "retrieval_poisoning": {
                    "family": "retrieval_poisoning",
                    "asr": 0.80, "asr_ci95": [0.76, 0.84], "n": 470,
                },
            },
            "calibration": {},
        }
        payload["ranked"][1]["detail"] = {
            "families": {
                "canary_leakage": {
                    "family": "canary_leakage",
                    "asr": 0.10, "asr_ci95": [0.07, 0.14], "n": 470,
                },
                "retrieval_poisoning": {
                    "family": "retrieval_poisoning",
                    "asr": 0.60, "asr_ci95": [0.55, 0.65], "n": 470,
                },
            },
            "calibration": {},
        }
        return payload

    def test_phone_heatmap_leads_with_highest_impact_family(self):
        # The phone heatmap orders its columns by average
        # attack success, so retrieval poisoning (mean 0.70
        # here) leads, while the desktop table keeps payload
        # order (canary first).
        page = leaderboard_to_html(self._families_payload())
        tables = re.findall(r"<table\b.*?</table>", page, flags=re.S)
        self.assertEqual(len(tables), 2)
        desk_head = re.findall(r"<th[^>]*>(.*?)</th>", tables[0])
        phone_head = re.findall(r"<th[^>]*>(.*?)</th>", tables[1])
        self.assertIn("canary leakage", desk_head[1].lower())
        self.assertIn("retrieval poisoning", phone_head[1].lower())
        self.assertIn('class="heat-wrap heat-m"', page)
        self.assertIn('class="heat-wrap heat-d"', page)

    def test_phone_scatter_shows_every_point(self):
        # The phone scatter is its own narrower form carrying
        # every plotted point and label, not a clipped copy of
        # the desktop chart.
        page = leaderboard_to_html(_payload())
        start = page.index('class="chart scatter-m"')
        start = page.rindex("<svg", 0, start)
        phone = page[start:page.index("</svg>", start)]
        # The phone plot runs taller than the desktop aspect
        # (pass 16), spreading close pairs along the ASR axis
        # so two near-coincident points keep a visible seam.
        self.assertIn('viewBox="0 0 352 388"', phone)
        # Phone markers are drawn smaller than the desktop
        # discs (r 4.5 with a 5 moat, against 6 and 7), so
        # close points stay separate glyphs at phone scale.
        # Pass 14 measured the closest real pair still
        # touching at r 5 and shrank the disc further; pass
        # 15 trimmed the moats so the closest pair's halos
        # sit just clear of each other.
        self.assertEqual(phone.count('class="pt"'), 4)
        self.assertIn('r="5"', phone)
        self.assertNotIn('r="8"', phone)
        self.assertIn("shieldstral-1.0", phone)

    def test_huge_asr_renders_bounded(self):
        # A corrupt ASR far past 100 percent must not explode
        # the render or raise: axes cap and gridlines coarsen.
        payload = _payload()
        payload["ranked"][0]["asr_conditional"] = 100000.0
        payload["ranked"][0]["asr_ci95"] = [90000.0, 110000.0]
        page = leaderboard_to_html(payload)
        self.assertLess(len(page), 1_000_000)

    def test_extreme_asr_does_not_raise(self):
        # Rates whose decimal expansion exceeds the default
        # context precision, and magnitudes whose ceiling
        # overflows, render as data like any other.
        for bad in (1e25, 1e308):
            payload = _payload()
            payload["ranked"][0]["asr_conditional"] = bad
            payload["ranked"][0]["asr_ci95"] = [bad, bad]
            page = leaderboard_to_html(payload)
            self.assertIn("shieldstral-1.0", page)

    def test_negative_heatmap_rate_prints_signed_value(self):
        # A negative family rate (corrupt data) prints its
        # signed whole percent in the visible cell, agreeing
        # with the exact figure in the cell's own text.
        payload = self._families_payload()
        payload["ranked"][0]["detail"]["families"][
            "canary_leakage"]["asr"] = -0.20
        page = leaderboard_to_html(payload)
        self.assertIn('<span aria-hidden="true">-20</span>', page)
        self.assertIn("canary leakage -20.0%", page)

    def test_slash_terminated_display_name_still_names(self):
        # A display name ending in a slash shortens to the
        # last non-empty segment, never to a blank.
        payload = _payload()
        payload["ranked"][0]["display_name"] = "vendor/model-x/"
        page = leaderboard_to_html(payload)
        self.assertIn("model-x", page)

    def test_scatter_states_tied_bands_inside_the_panel(self):
        # The scatter panel cropped or shared alone must not
        # present the point gaps as separations the page
        # elsewhere calls ties: the band statement is inside
        # the SVG, in both forms.
        payload = _payload()
        payload["ranked"][1]["asr_conditional"] = 0.23
        payload["ranked"][1]["asr_ci95"] = [0.20, 0.27]
        page = leaderboard_to_html(payload)
        self.assertEqual(page.count("tied bands 1–2"), 2)

    def test_scatter_label_guard_keeps_unsolved_names_on_panel(self):
        # A model with no solved label placement, sitting at
        # an extreme cost, must not start its phone label at
        # the viewBox edge and clip it off the panel: the
        # placement flips to end-anchored inside the edge.
        payload = _payload()
        payload["ranked"][0]["display_name"] = "verylongmodelname-x1"
        payload["ranked"][0]["total_cost_usd"] = 95.0
        page = leaderboard_to_html(payload)
        start = page.index('class="chart scatter-m"')
        start = page.rindex("<svg", 0, start)
        phone = page[start:page.index("</svg>", start)]
        self.assertIn('x="350.0"', phone)
        self.assertIn('text-anchor="end">verylongmodelname-x1', phone)

    def test_unpriced_calls_mark_costs_as_lower_bounds(self):
        # A run whose families costed fewer calls than they
        # timed carries a lower bound, and its card and the
        # KPI tile say so; a fully priced run's card does not.
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {
                "canary_leakage": {
                    "family": "canary_leakage", "asr": 0.05,
                    "n_costed_calls": 800, "n_latency_calls": 840,
                },
            },
            "calibration": {},
        }
        page = leaderboard_to_html(payload)
        self.assertEqual(page.count("COST · LOWER BOUND"), 1)
        # The tile marks the endpoint that is a bound, in
        # place: the fixture's top cost is the unpriced run
        # itself, so its name carries the mark, and no
        # blanket plural mark mislabels the exact low end.
        self.assertIn("SHIELDSTRAL-1.0 (LOWER BOUND)", page)
        self.assertNotIn("LOWER BOUNDS", page)

    def test_cards_caption_escapes_family_names(self):
        # A hostile family id reaches the cards caption's
        # spark-order list, the heatmap headers and the card
        # spark labels: every surface must print it inert.
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {
                "<script>alert(1)</script>": {
                    "family": "<script>alert(1)</script>",
                    "asr": 0.5, "n_eligible": 400,
                },
            },
            "calibration": {},
        }
        page = leaderboard_to_html(payload)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)

    def test_extreme_family_asr_renders(self):
        # A family rate at the top of the float range fills
        # its spark track instead of raising on the height
        # rounding (pass 13).
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {
                "canary_leakage": {
                    "family": "canary_leakage", "asr": 1e308,
                    "n_eligible": 400,
                },
            },
            "calibration": {},
        }
        page = leaderboard_to_html(payload)
        self.assertIn("shieldstral-1.0", page)

    def test_extreme_severity_reach_renders(self):
        # A severity interval reaching past the whole scale
        # skips the caption's widest-reach clause instead of
        # raising on its ceiling (pass 13).
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {},
            "severities": {
                "critical": {"flip_rate_raw": 0.1,
                             "flip_rate_ci95": [0.0, 1e308]},
            },
            "calibration": {},
        }
        page = leaderboard_to_html(payload)
        self.assertIn("shieldstral-1.0", page)
        self.assertNotIn("confidence intervals run widest", page)

    def test_mixed_case_counts_are_not_asserted(self):
        # Runs of different sizes share no per-run case
        # count: the tile's claim disappears and the footer
        # provenance discloses the variation instead of the
        # page asserting one run's count for every run.
        payload = _payload()
        payload["ranked"][0]["n_cases"] = 100
        payload["ranked"][1]["n_cases"] = 200
        page = leaderboard_to_html(payload)
        self.assertNotIn("PAIRED CASES EACH", page)
        self.assertIn("case counts vary by run", page)

    def test_mixed_suites_are_not_asserted(self):
        # Two runs naming different suites print no single
        # suite for the page.
        payload = _payload()
        payload["ranked"][0]["suite"] = "suite-a"
        payload["ranked"][1]["suite"] = "suite-b"
        page = leaderboard_to_html(payload)
        self.assertIn("Peira suite n/a", page)

    def test_duplicate_run_id_names_both_runs(self):
        # Two distinct runs can share a run_id across
        # trials: the footer run notes name each affected
        # run on the page, not only the first.
        payload = _payload()
        payload["ranked"][0]["run_id"] = "google-v2-trial"
        payload["ranked"][0]["display_name"] = "Google One"
        payload["ranked"][1]["run_id"] = "google-v2-trial"
        payload["ranked"][1]["display_name"] = "Google Two"
        page = leaderboard_to_html(payload)
        self.assertIn("cases of the Google One run", page)
        self.assertIn("cases of the Google Two run", page)

    def test_non_dict_payload_renders_empty_state(self):
        for bad in (None, "junk", [1, 2]):
            page = leaderboard_to_html(bad)
            self.assertIn("peira leaderboard", page)

    def test_bad_payload_hash_falls_back(self):
        # A caller-supplied hash that is not a plausible hex
        # digest is never printed as the payload's hash: the
        # canonical-JSON fallback takes its place.
        page = leaderboard_to_html(_payload(), payload_sha256=12345)
        self.assertNotIn("payload sha256 12345", page)
        self.assertRegex(page, r"payload sha256 [0-9a-f]{16}…")

    def test_garbage_date_carries_no_frame_claim(self):
        # An unparseable run stamp passes through raw; the
        # local-frame suffix is claimed only for real
        # converted dates.
        payload = _payload()
        payload["ranked"][0]["created_utc"] = "not-a-date"
        page = leaderboard_to_html(payload)
        self.assertNotIn("(local dates, America/New_York)", page)

    def test_scatter_marks_lower_bound_costs_inside_the_panel(self):
        # The scatter's own text (its description and the
        # in-panel line) carries the lower-bound caveat, so
        # the panel cropped alone, or reached through a
        # graphics list, does not present bounds as exact.
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {
                "canary_leakage": {
                    "family": "canary_leakage", "asr": 0.05,
                    "n_costed_calls": 800, "n_latency_calls": 840,
                },
            },
            "calibration": {},
        }
        page = leaderboard_to_html(payload)
        self.assertIn("$1.23 (lower bound) at", page)
        # Both forms carry the caveat inside the panel
        # (pass 23). The desktop form always takes the full
        # sentence. The phone form takes the full sentence
        # when it clears the tied-bands line on the shared
        # row and the key form ("lower bound dots", the
        # passes 14 to 16 form) when only the key form
        # clears it: at the phone text size the full
        # sentence and the bands line together run wider
        # than the plot and overprinted into one merged
        # string that destroyed both disclosures (pass 33,
        # reversing pass 23's sentence unification for the
        # phone form only; the panel's legend row, the
        # section caption and the description carry the
        # full statement there).
        self.assertGreaterEqual(
            page.count("dots mark the lower bound costs"
                       "</text>"), 1)
        scatters = [
            s for s in re.findall(
                r'<svg viewBox="0 0 \d+ \d+".*?</svg>',
                page, re.S)
            if "cost per run" in s]
        self.assertEqual(2, len(scatters))
        for svg in scatters:
            self.assertTrue(
                "dots mark the lower bound costs</text>" in svg
                or ">lower bound dots</text>" in svg)
        # The bound is marked on the point itself in both
        # scatter forms: one pale centre dot on the
        # lower-bound run's point plus the legend swatch's
        # reproduction of it, per form (pass 15: a single
        # pale mark on both classes, where a ground-coloured
        # dot read as a hole in the disc).
        self.assertEqual(page.count('r="2" fill="#f4f8f2"'), 4)
        self.assertIn("lower bound cost", page)

    def test_kpi_retrieval_attribution_names_the_flag_cost(self):
        # When a flagged model holds the retrieval range's low
        # endpoint, the tile frames it as the range's low end
        # and names the cost of the flag, so the KPI row
        # cropped alone cannot crown a flagged model with a
        # superlative (passes 14 and 15).
        payload = _payload()
        fam = {"family": "retrieval_poisoning", "asr": 0.80,
               "n_eligible": 400}
        payload["ranked"][0]["detail"] = {
            "families": {"retrieval_poisoning": fam},
            "calibration": {},
        }
        fam2 = {"family": "retrieval_poisoning", "asr": 0.85,
                "n_eligible": 400}
        payload["ranked"][1]["detail"] = {
            "families": {"retrieval_poisoning": fam2},
            "calibration": {},
        }
        fam3 = {"family": "retrieval_poisoning", "asr": 0.50,
                "n_eligible": 400}
        payload["unranked"][0]["detail"] = {
            "families": {"retrieval_poisoning": fam3},
            "calibration": {},
        }
        page = leaderboard_to_html(payload)
        self.assertIn("LOW END IS FLAGGED", page)
        # NO RANK is bound with a no-break space inside it
        # (pass 18), so the unit can never orphan its second
        # word onto a line of its own at narrow widths.
        self.assertIn("AT 50.0%&nbsp;· NO&nbsp;RANK", page)

    def test_card_stat_labels_anchor_their_bases(self):
        # The benign accuracy label names the base its figure
        # rests on, and the robust tax label names its anchor,
        # so a card cropped alone cannot attach the eligible
        # count to the accuracy or read a zero tax as an
        # absolute score (pass 14). The run that sets both
        # benchmarks is its own comparison, and its label
        # says so instead of implying a rival (pass 15).
        page = leaderboard_to_html(_payload())
        self.assertIn("BENIGN ACC · DECIDED VARIANTS", page)
        self.assertIn("ROBUST TAX · VS BEST RANKED RUNS", page)
        # The setter label carries the ranked scope: a
        # flagged run can hold a higher raw benign figure
        # than the setter, and the unscoped superlative
        # contradicted that figure on the same page
        # (passes 24, 25, 30; reconciliation ledger Theme 9).
        self.assertIn("ROBUST TAX · IT SETS BOTH RANKED "
                      "BENCHMARKS", page)
        self.assertNotIn("IT SETS BOTH BENCHMARKS", page)

    def test_huge_integer_fields_render_as_missing(self):
        # A JSON integer past the float range (a 401-digit
        # literal parses to an int, not a float) must not take
        # the render down: it is treated as missing, the same
        # as a non-finite float (pass 15).
        for field in ("asr_conditional", "total_cost_usd",
                      "malformed_rate", "benign_accuracy"):
            payload = _payload()
            payload["ranked"][0][field] = 10 ** 400
            page = leaderboard_to_html(payload)
            self.assertIn("script&gt;", page)

    def test_scatter_extreme_asr_stays_on_the_panel(self):
        # A corrupt ASR past the axis (or below zero) clamps
        # to the panel edge in the scatter, as the hero chart
        # already clamps it: no inf geometry, and the point
        # is not silently lost off-panel (pass 15).
        for bad in (1e308, -1e308, 25.0, -0.5):
            payload = _payload()
            payload["ranked"][0]["asr_conditional"] = bad
            payload["ranked"][0]["asr_ci95"] = [bad, bad]
            page = leaderboard_to_html(payload)
            self.assertNotIn('cy="inf"', page)
            self.assertNotIn('cy="-inf"', page)
            self.assertNotIn('y="inf"', page)

    def test_subnormal_cost_renders(self):
        # The smallest subnormal cost pushes the log axis a
        # decade past the float range, where the decade tick
        # underflows to zero and its log raises: the render
        # survives and the point still plots (pass 15).
        payload = _payload()
        payload["ranked"][0]["total_cost_usd"] = 5e-324
        page = leaderboard_to_html(payload)
        self.assertIn("shieldstral-1.0", page)

    def test_extreme_malformed_rate_prints_no_inf_percent(self):
        # A malformed rate past 100 percent stops the strip
        # scale at the whole instead of printing an inf
        # ceiling on either form (pass 15).
        payload = _payload()
        payload["ranked"][0]["malformed_rate"] = 1e307
        page = leaderboard_to_html(payload)
        self.assertNotIn("inf%", page)

    def test_unserializable_payload_still_hashes(self):
        # Payload shapes parsed JSON cannot produce (a dict
        # with mixed-type keys, a self-referencing dict)
        # still render, with a stable fallback hash in the
        # provenance block rather than a dead render
        # (pass 15).
        payload = _payload()
        payload["extra"] = {1: "a", "b": 2}
        page = leaderboard_to_html(payload)
        self.assertIn("shieldstral-1.0", page)
        payload = _payload()
        payload["self"] = payload
        page = leaderboard_to_html(payload)
        self.assertIn("shieldstral-1.0", page)

    def test_negative_call_counts_are_not_lower_bound_evidence(self):
        # Call counts that cannot exist are corrupt, not
        # evidence: a negative costed count never marks its
        # run a lower bound on any surface (pass 15).
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {
                "canary_leakage": {
                    "family": "canary_leakage", "asr": 0.05,
                    "n_costed_calls": -5, "n_latency_calls": 840,
                },
            },
            "calibration": {},
        }
        page = leaderboard_to_html(payload)
        self.assertNotIn("COST · LOWER BOUND", page)
        self.assertEqual(page.count('r="2" fill="#f4f8f2"'), 0)

    def test_nameless_list_family_still_marks_lower_bound(self):
        # A family entry in list form with no family field
        # has no name to plot under, but its counts are
        # still evidence about the run's pricing (pass 15).
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": [{
                "asr": 0.05, "n_eligible": 400,
                "n_costed_calls": 800, "n_latency_calls": 840,
            }],
            "calibration": {},
        }
        page = leaderboard_to_html(payload)
        self.assertIn("COST · LOWER BOUND", page)

    def _cost_payload(self, specs):
        payload = _payload()
        rows = (payload["ranked"][0], payload["ranked"][1],
                payload["unranked"][0])
        for row, (cost, lb) in zip(rows, specs):
            row["total_cost_usd"] = cost
            if lb:
                row["detail"] = {
                    "families": {
                        "canary_leakage": {
                            "family": "canary_leakage",
                            "asr": 0.05, "n_costed_calls": 800,
                            "n_latency_calls": 840,
                        },
                    },
                    "calibration": {},
                }
            else:
                row.pop("detail", None)
        return payload

    def test_kpi_cost_tile_marks_low_end_behind_flagged_top(self):
        # The cost tile's low end keeps its lower-bound mark
        # when a flagged run tops the spread and the low end
        # is never named: deciding marks from one
        # representative run per tile let the endpoint go
        # unmarked (pass 15).
        page = leaderboard_to_html(self._cost_payload(
            [(1.00, True), (5.00, False), (10.00, False)]))
        self.assertIn("TOP COST IS FLAGGED", page)
        # The low end is named now (the flagged top no longer
        # replaces the whole label, pass 18), so its bound
        # mark rides on its name, in place.
        self.assertIn("SHIELDSTRAL-1.0 (LOWER BOUND)", page)
        # A single shared cost is a lower bound when any run
        # at that cost is one, whichever is listed first.
        for specs in ([(2.00, False), (2.00, True), (2.00, False)],
                      [(2.00, True), (2.00, False), (2.00, False)]):
            page = leaderboard_to_html(self._cost_payload(specs))
            self.assertIn("COST PER RUN (LOWER BOUND)", page)

    def test_lower_bound_cost_floors_at_the_cent(self):
        # A lower bound printed at the cent must stay a
        # bound: nearest rounding stated the recorded
        # $4.2757 floor as $4.28 on the card, in both
        # scatter descriptions and on the tile, a floor
        # above the figure the run actually recorded
        # (pass 38, red team).
        page = leaderboard_to_html(self._cost_payload(
            [(4.2757, True), (1.00, False), (2.00, False)]))
        self.assertIn("COST · LOWER BOUND", page)
        self.assertIn("$4.27 (lower bound)", page)
        self.assertIn("$4.27", page)
        self.assertNotIn("$4.28", page)

    def test_exact_cost_rounds_to_the_nearest_cent(self):
        # The floor rule belongs to bounds alone: an exact
        # recorded cost keeps the page's nearest-cent
        # rounding (pass 38 guard pin; passes either way
        # unless the bound rule leaks onto exact costs).
        page = leaderboard_to_html(self._cost_payload(
            [(11.0859, False), (1.00, False), (2.00, False)]))
        self.assertIn("$11.09", page)
        self.assertNotIn("$11.08", page)

    def test_lower_bound_tile_endpoint_floors(self):
        # The tile's marked endpoint floors like the card:
        # a flagged lower-bound run topping the spread
        # states its floor, not the rounded-up figure
        # (pass 38).
        page = leaderboard_to_html(self._cost_payload(
            [(0.50, False), (1.00, False), (4.2757, True)]))
        self.assertIn("TOP COST IS FLAGGED", page)
        self.assertIn("≥$4.27", page)
        self.assertNotIn("$4.28", page)

    def test_subcent_lower_bound_still_shows_floored(self):
        # Flooring cannot collapse a sub-cent bound to the
        # free-run figure: the precision rises until the
        # floored figure shows, on the card and the tile
        # alike (pass 38).
        page = leaderboard_to_html(self._cost_payload(
            [(0.0075, True), (1.00, False), (2.00, False)]))
        self.assertIn("$0.007", page)
        self.assertIn("≥$0.007", page)
        # The stated bound never rounds up to the cent
        # figure (the scatter's $0.01 axis tick is scale,
        # not a stated cost, and stands).
        self.assertNotIn("≥$0.01", page)

    def test_heat_caption_carries_the_bases_only(self):
        # The heat caption states the bases the cells rest
        # on and nothing the panel's own reading line
        # already states: the cell definition, the row
        # order, the ties and the flagged rows' lack of
        # rank stand in the note inside the panel, and the
        # stacked repetition cost some 300px of text
        # before the first phone cell (pass 38, craft and
        # mobile). The scroll fact is stated once, by the
        # line at the chart's head.
        payload = _payload()
        fam = {"retrieval_poisoning": {"asr": 0.827,
                                       "n_eligible": 400},
               "verbosity": {"asr": 0.30, "n_eligible": 358}}
        for row in payload["ranked"]:
            row["detail"] = {"families": dict(fam),
                             "calibration": {}}
        page = leaderboard_to_html(payload)
        heat = page[page.index('<section id="heatmap"'):
                    page.index('<section id="cost"')]
        cap = heat[heat.index('<p class="cap">'):
                   heat.index('</p>')]
        self.assertIn(
            "Each cell rests on 358 to 400 eligible cases.",
            cap)
        self.assertNotIn("Cell values are family", cap)
        self.assertNotIn("rows ordered by overall ASR", cap)
        self.assertNotIn("flagged rows say no rank", cap)
        self.assertNotIn("on small screens the families",
                         cap)
        self.assertIn("rows in overall ASR order", heat)
        self.assertIn("flagged rows carry no rank", heat)
        self.assertNotIn("more families sit to the right",
                         page)
        self.assertIn(
            "the remaining families sit to the right · "
            "scroll sideways", page)

    def test_kpi_note_joins_the_caption_register(self):
        # Every section caption indents to the heading-text
        # line; the note under the KPI tiles sat flush at
        # the module edge, the one caption-function line
        # out of register (pass 38, craft).
        page = leaderboard_to_html(_payload())
        self.assertIn(
            ".kpi-note{font-size:12px;color:#8a97a3;"
            "margin:2px 0 0 14px}", page)

    def test_kpi_numerals_step_down_at_narrow_widths(self):
        # Below about 350px the phone fit system's 20px
        # step outruns the tile and the range numerals'
        # final glyph paints past the tile border: one
        # more step keeps every numeral inside its tile
        # (pass 38, mobile).
        page = leaderboard_to_html(_payload())
        self.assertIn(
            "@media(max-width:360px){.kpi-num{font-size:17px}"
            ".kpi.vmid .kpi-num{font-size:16px}}", page)

    def test_kpi_retrieval_single_value_is_not_a_range(self):
        # One distinct retrieval value across the carriers
        # prints as the one figure, not a degenerate range,
        # and its flagged carriers are counted (pass 15;
        # the count form replaced the bare flagged mark for
        # mixed carriers in pass 22, since the figure here is
        # carried by ranked runs too).
        payload = _payload()
        for row in (payload["ranked"][0], payload["ranked"][1],
                    payload["unranked"][0]):
            row["detail"] = {
                "families": {
                    "retrieval_poisoning": {
                        "family": "retrieval_poisoning",
                        "asr": 0.50, "n_eligible": 400,
                    },
                },
                "calibration": {},
            }
        page = leaderboard_to_html(payload)
        self.assertIn("RETRIEVAL POISONING ASR", page)
        self.assertNotIn("50.0–50.0%", page)
        self.assertIn("1 OF 3 CARRIERS FLAGGED", page)

    def test_hero_panel_states_its_reading_direction(self):
        # The ranking panel carries its direction and the
        # hatch meaning inside the chart, and the phone
        # list's scale line states the direction too.
        page = leaderboard_to_html(_payload())
        self.assertIn("lower is stronger · hatched bars "
                      "carry no rank", page)
        self.assertIn("% · lower is stronger", page)

    def test_family_entry_keyed_only_by_mapping_key(self):
        # A family detail entry whose dict lacks the inner
        # family field is keyed by its mapping key, not
        # silently dropped from the page's family surfaces.
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {
                "canary_leakage": {"asr": 0.05, "n_eligible": 400},
            },
            "calibration": {},
        }
        page = leaderboard_to_html(payload)
        self.assertIn("canary leakage 5.0%", page)

    def test_footer_dates_name_the_local_frame(self):
        # The run window is stated in the trial record's
        # local frame, and the footer names the frame so a
        # verifier holding the payload's UTC stamps does not
        # read the window as excluding a run.
        payload = _payload()
        payload["ranked"][0]["created_utc"] = "2026-10-13T00:07:00+00:00"
        page = leaderboard_to_html(payload)
        self.assertIn("(local dates, America/New_York)", page)

    def test_kpi_cost_spread_ignores_nonpositive_costs(self):
        # The cost tile states the spread of recorded costs on
        # the same rule as the scatter, positive costs only, so
        # a zero or negative entry cannot drag the spread to a
        # figure no plotted point carries.
        payload = _payload()
        payload["unranked"][0]["total_cost_usd"] = -5.0
        page = leaderboard_to_html(payload)
        self.assertIn("$0.50–$1.23", page)
        self.assertNotIn("$-5.00–$1.23", page)

    def test_calib_share_is_the_counts_own_share_of_eligible(self):
        # The share beside the calibration count divides the
        # count by the run's eligible cases, the base the card
        # itself prints. The payload's confidence coverage is a
        # different quantity (a share of all cases, ineligible
        # included) and must not ride beside this count: on the
        # real payload the two contradicted each other on five
        # cards, one printing 98.7% beside two identical counts
        # (pass 17).
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {},
            "calibration": {
                "attacked": {"n": 300, "brier": 0.13},
                "confidence_coverage": {"attacked": 0.5},
            },
        }
        page = leaderboard_to_html(payload)
        # The label names its arm with the share (pass 18).
        self.assertIn("CALIB N · ATTACKED · SHARE OF ELIGIBLE",
                      page)
        self.assertIn("300 · 75.0%", page)
        self.assertNotIn("300 · 50.0%", page)
        # A count past its own base is corrupt and prints bare
        # rather than as a share over 100 percent.
        payload["ranked"][0]["detail"]["calibration"][
            "attacked"]["n"] = 500
        page = leaderboard_to_html(payload)
        self.assertNotIn("125.0%", page)
        self.assertNotIn("500 ·", page)
        # With the share suppressed the label drops to the
        # bare count name, and the footer's share sentence
        # stops claiming one beside every count (pass 18).
        self.assertIn(
            '<span class="stat-lab">CALIB N</span>', page)
        self.assertIn("The share beside a calibration count",
                      page)

    def test_gate_note_and_captions_derive_from_the_value(self):
        # The gate note follows the printed malformed value,
        # not the row's rank status: a ranked row over the
        # limit says over, and no caption attributes every
        # hatched bar's flag to the malformed rule (pass 17).
        payload = _payload()
        # Both ranked cards sit over the limit here, so the
        # at-or-under note must vanish from the page entirely.
        payload["ranked"][0]["malformed_rate"] = 0.11
        payload["ranked"][1]["malformed_rate"] = 0.12
        page = leaderboard_to_html(payload)
        self.assertIn("Malformed response rate above 5%", page)
        self.assertNotIn(
            "Malformed response rate at or under 5%", page)
        self.assertIn("hatched bars carry", page)
        self.assertNotIn("hatched bars failed", page)
        self.assertIn(
            "a rank requires a malformed response rate at "
            "or under 5%", page)
        self.assertIn(
            "bars past the line are over the 5% admission limit",
            page)
        self.assertIn(
            "bars past it are over the 5% admission limit", page)
        self.assertNotIn("are flagged and carry no rank", page)
        payload = _payload()
        payload["ranked"][0]["malformed_rate"] = 0.03
        page = leaderboard_to_html(payload)
        self.assertIn(
            "Malformed response rate at or under 5%", page)

    def test_card_labels_name_the_attacked_run(self):
        # Latency and calibration labels carry the attacked
        # qualifier on the card's own face, because a cropped
        # card is the share unit and the section caption's
        # scoping does not travel with it (pass 17).
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {},
            "calibration": {"attacked": {"brier": 0.13}},
        }
        page = leaderboard_to_html(payload)
        for label in ("LATENCY P50 · ATTACKED",
                      "LATENCY P95 · ATTACKED",
                      "ECE · ATTACKED", "BRIER · ATTACKED"):
            self.assertIn(label, page)

    def test_lower_bound_dot_and_flagged_legend_swatch(self):
        # The lower bound dot is a pale disc with a dark stroke
        # in both scatter forms. The legend keys the glyph
        # components separately, so the flagged legend swatch
        # is a bare ring and never carries the dot: the
        # pass-16 rule that dotted it whenever every flagged
        # point was dotted taught that the dot belonged to
        # the flagged glyph (passes 24, 25, 27;
        # reconciliation ledger Theme 4).
        payload = _payload()
        fam = {"families": {"canary_leakage": {
            "family": "canary_leakage", "asr": 0.05,
            "n_costed_calls": 800, "n_latency_calls": 840}},
            "calibration": {}}
        payload["unranked"][0].update({
            "asr_conditional": 0.30, "asr_ci95": [0.25, 0.35],
            "total_cost_usd": 0.75, "n_eligible": 400,
            "benign_accuracy": 0.90})
        payload["unranked"][0]["detail"] = fam
        page = leaderboard_to_html(payload)
        dot = 'fill="#f4f8f2" stroke="#10141a"'
        # One flagged point in two scatter forms, and the
        # lower bound legend row's exemplar disc in both
        # forms. The flagged swatch contributes no dot.
        self.assertEqual(page.count(dot), 4)
        # The same run fully priced: no dots anywhere.
        fam["families"]["canary_leakage"]["n_costed_calls"] = 840
        page = leaderboard_to_html(payload)
        self.assertEqual(page.count(dot), 0)

    def test_kpi_floor_mark_binds_its_own_figure(self):
        # A marked endpoint breaks the range dash for a word,
        # so the floor mark cannot be read as covering the
        # whole spread; an all exact spread keeps the dash
        # (pass 17, pass 16 mark).
        page = leaderboard_to_html(_payload())
        self.assertIn("$0.50–$1.23", page)
        self.assertNotIn("to ≥$", page)
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {"canary_leakage": {
                "family": "canary_leakage", "asr": 0.05,
                "n_costed_calls": 800, "n_latency_calls": 840}},
            "calibration": {}}
        page = leaderboard_to_html(payload)
        self.assertIn("$0.50 to ≥$1.23", page)

    def test_phone_scatter_text_floor_is_pinned(self):
        # The phone scatter's axis and label sizes are a ruled
        # legibility floor, not incidental CSS (pass 16 pin).
        page = leaderboard_to_html(_payload())
        self.assertIn("svg.scatter-m .s-axis{font-size:12px}", page)
        self.assertIn(
            "svg.scatter-m .s-lab{font-size:12.5px}", page)

    def test_bidi_and_zero_width_controls_never_reach_the_page(self):
        # Invisible Unicode controls in a name are a visual
        # spoof surface: a right-to-left override can reorder
        # the glyphs around a model or family name while the
        # underlying text stays innocent (pass 17).
        payload = _payload()
        payload["ranked"][0]["adapter_name"] = "shield\u202estral"
        payload["ranked"][0]["detail"] = {
            "families": {"canary\u200b_leakage": {
                "family": "canary\u200b_leakage", "asr": 0.5,
                "n_eligible": 400}},
            "calibration": {}}
        page = leaderboard_to_html(payload)
        self.assertNotIn("\u202e", page)
        self.assertNotIn("\u200b", page)
        self.assertIn("shieldstral", page)

    def test_negative_zero_prints_unsigned(self):
        # Negative zero is a float artefact, not a value: it
        # prints as plain zero in every formatter (pass 17).
        payload = _payload()
        payload["ranked"][0].update({
            "asr_conditional": -0.0, "total_cost_usd": -0.0,
            "latency_ms_p50_attacked": -0.0})
        page = leaderboard_to_html(payload)
        self.assertNotIn("-0.0%", page)
        self.assertNotIn("$-0.00", page)
        self.assertNotIn("-0ms", page)
        self.assertIn("0.0%", page)

    def test_family_display_names_never_collide(self):
        # Two family keys whose prose forms coincide stay
        # distinguishable: both keep their prose form plus a
        # position suffix rather than sharing one printed
        # name (pass 17 fell back to the raw keys; pass 18
        # keeps the reading in prose).
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {
                "a_b": {"family": "a_b", "asr": 0.1,
                        "n_eligible": 400},
                "a b": {"family": "a b", "asr": 0.2,
                        "n_eligible": 400},
            },
            "calibration": {}}
        page = leaderboard_to_html(payload)
        # One header per family per heat table (desktop, phone).
        self.assertEqual(page.count(">a b (1)</th>"), 2)
        self.assertEqual(page.count(">a b (2)</th>"), 2)
        self.assertNotIn(">a_b</th>", page)
        self.assertNotIn(">a b</th>", page)

    def test_all_flagged_retrieval_range_tile_is_marked(self):
        # When every run behind the retrieval range is flagged,
        # the range tile's label says so, as the single value
        # form already did (pass 17).
        payload = _payload()
        rp = {"families": {"retrieval_poisoning": {
            "family": "retrieval_poisoning", "asr": 0.5,
            "n_eligible": 400}}, "calibration": {}}
        payload["unranked"][0]["detail"] = rp
        extra = dict(payload["unranked"][0])
        extra["adapter_name"] = "second-flagged"
        extra["detail"] = {"families": {"retrieval_poisoning": {
            "family": "retrieval_poisoning", "asr": 0.8,
            "n_eligible": 400}}, "calibration": {}}
        payload["unranked"].append(extra)
        page = leaderboard_to_html(payload)
        # The label's joins print as no-break entities in the
        # HTML; the text a reader sees is the marked range.
        self.assertIn(
            "RETRIEVAL POISONING ASR RANGE&nbsp;· "
            "FLAGGED&nbsp;· NO&nbsp;RANK", page)
        self.assertIn("50.0–80.0%", page)

    def test_print_keeps_hero_rows_whole(self):
        # The print form is the phone hero list; its rows carry
        # break-inside avoid like cards and panels, so a row's
        # qualifiers never orphan onto the next page (pass 17).
        page = leaderboard_to_html(_payload())
        self.assertIn(".mb-row{break-inside:avoid}", page)

    def test_flagged_card_spark_bars_drop_the_ranked_green(self):
        # Green is the ranked fill everywhere else on the page;
        # a flagged card's family bars print grey, with the
        # retrieval spike keeping its orange on every card
        # (pass 17).
        payload = _payload()
        fams = {"families": {
            "canary_leakage": {"family": "canary_leakage",
                               "asr": 0.5, "n_eligible": 400},
            "retrieval_poisoning": {
                "family": "retrieval_poisoning", "asr": 0.6,
                "n_eligible": 400}}, "calibration": {}}
        payload["unranked"][0]["detail"] = fams
        payload["ranked"][0]["detail"] = fams
        page = leaderboard_to_html(payload)
        self.assertIn('class="spark dim"', page)
        self.assertIn('class="spark hot"', page)
        # The caption's colour claim is scoped to the bar
        # FILL (the retrieval spike and the dotted n/a slot
        # are not fill), and it captions both exceptions
        # (pass 18).
        self.assertIn(
            "bar fill is green on ranked cards and grey on "
            "flagged cards", page)
        self.assertIn(
            "a dotted outline marks a family a model does "
            "not carry", page)

    def test_phone_hero_flagged_malformed_prints_amber(self):
        # The phone hero is a malformed surface too: a flagged
        # value there takes the flagged amber, as the desktop
        # hero and strip already did (pass 17).
        payload = _payload()
        payload["unranked"][0].update({
            "asr_conditional": 0.30, "asr_ci95": [0.25, 0.35],
            "malformed_rate": 0.0728})
        page = leaderboard_to_html(payload)
        self.assertIn('class="nb malf-flag"', page)
        self.assertIn(".mb-sub .malf-flag{color:#e8a33d}", page)

    # ------------------------------------------------ pass 19

    def test_zero_calibration_count_without_scores_is_na(self):
        # A calibration count of exactly zero with no ECE or
        # Brier anywhere in the block is no calibration data:
        # the pair prints n/a, never a measured "0 · 0.0%"
        # share over an empty base (pass 19).
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {},
            "calibration": {"attacked": {"n": 0}},
        }
        del payload["ranked"][0]["ece_attacked"]
        page = leaderboard_to_html(payload)
        self.assertNotIn("0 · 0.0%", page)
        self.assertIn(
            '<span class="stat-lab">CALIB N</span>'
            '<span class="stat-val">n/a</span>', page)
        # A zero count WITH a score in the block keeps the
        # count: the absence rule needs both to be missing.
        payload["ranked"][0]["detail"]["calibration"][
            "attacked"] = {"n": 0, "ece": 0.31}
        page = leaderboard_to_html(payload)
        self.assertIn("0 · 0.0%", page)
        # The Brier alone is a score too: same branch, pinned
        # separately so neither half of the rule can regress
        # behind the other (pass 21).
        payload["ranked"][0]["detail"]["calibration"][
            "attacked"] = {"n": 0, "brier": 0.21}
        page = leaderboard_to_html(payload)
        self.assertIn("0 · 0.0%", page)

    def test_missing_value_escapes_to_nothing(self):
        # The escape gate turns a missing value into empty
        # text, never the literal word for it (pass 19).
        from peira.report_html import _esc
        self.assertEqual(_esc(None), "")

    # ------------------------------------------------ pass 18

    def test_gate_edge_rates_print_two_decimals(self):
        # Rates that round to 5.0 percent without being exactly
        # 5 percent carry opposite gate verdicts in their
        # unprinted digits, so they print at two decimals on
        # the malformed surfaces (pass 18).
        payload = _payload()
        payload["ranked"][0]["malformed_rate"] = 0.0504
        payload["ranked"][1]["malformed_rate"] = 0.0496
        page = leaderboard_to_html(payload)
        self.assertIn("5.04%", page)
        self.assertIn("4.96%", page)
        # The value-derived notes follow the unrounded values.
        self.assertIn("Malformed response rate above 5%", page)
        self.assertIn(
            "Malformed response rate at or under 5%", page)

    def test_flagged_gate_note_derives_from_the_value(self):
        # A flagged card's registry reason can claim the gate
        # while its own printed rate sits under it: the note
        # follows the value, not the claim (pass 18). The
        # recorded reason still prints, labelled as the
        # record, so the derivation no longer deletes a
        # registry reason from the page (passes 24 and 26).
        payload = _payload()
        payload["unranked"][0].update({
            "reason": "ranking-ineligible: malformed_rate above 5%",
            "malformed_rate": 0.03,
        })
        page = leaderboard_to_html(payload)
        self.assertIn(
            "Malformed response rate at or under 5%", page)
        self.assertIn(
            "Reason on record · Malformed response rate "
            "above 5%", page)

    def test_calib_share_edges_print_two_decimals(self):
        # A share that rounds to 100.0 or 0.0 percent without
        # being exact prints at two decimals; an exact share
        # keeps the one-decimal form (pass 18).
        payload = _payload()
        payload["ranked"][0]["n_eligible"] = 10000
        payload["ranked"][0]["detail"] = {
            "families": {},
            "calibration": {"attacked": {"n": 9996}},
        }
        payload["ranked"][1]["n_eligible"] = 10000
        payload["ranked"][1]["detail"] = {
            "families": {},
            "calibration": {"attacked": {"n": 10000}},
        }
        page = leaderboard_to_html(payload)
        self.assertIn("9,996 · 99.96%", page)
        self.assertIn("10,000 · 100.0%", page)

    def test_ece_comes_from_the_calibration_block(self):
        # The card's ECE is read from the calibration block its
        # neighbouring figures come from, not from a flat field
        # that disagrees with it (pass 18).
        payload = _payload()
        payload["ranked"][0]["ece_attacked"] = 0.04
        payload["ranked"][0]["detail"] = {
            "families": {},
            "calibration": {"attacked": {"ece": 0.31}},
        }
        page = leaderboard_to_html(payload)
        self.assertIn(
            'ECE · ATTACKED</span>'
            '<span class="stat-val">0.310</span>', page)

    def test_model_name_collisions_are_disambiguated(self):
        # Two models whose short names coincide after cleaning
        # take position suffixes at entry construction, so no
        # chart prints them as one model (pass 18).
        payload = _payload()
        payload["ranked"][0]["display_name"] = "acme/model-x"
        payload["ranked"][1]["display_name"] = "other/model-x"
        page = leaderboard_to_html(payload)
        self.assertIn("model-x (1)", page)
        self.assertIn("model-x (2)", page)

    def test_collision_suffix_joins_on_the_stripped_base(self):
        # The collision test folds edge whitespace away, so a
        # name recorded with a trailing space collides with
        # its trimmed twin and takes a suffix; the suffix joins
        # on the stripped base, so the label prints one space
        # before it, never a doubled space (pass 39).
        payload = _payload()
        payload["ranked"][0]["display_name"] = "acme/model-x "
        payload["ranked"][1]["display_name"] = "other/model-x"
        page = leaderboard_to_html(payload)
        self.assertIn("model-x (1)", page)
        self.assertIn("model-x (2)", page)
        self.assertNotIn("model-x  (1)", page)

    def test_invisible_padding_never_blanks_a_name(self):
        # Cleaning runs before truncation: a name padded with
        # zero-width spaces still prints its visible text, the
        # joiner inside an emoji name survives, and the
        # grapheme joiner is stripped (pass 18). The invisible
        # characters are written as escapes so this file
        # carries none of them literally.
        payload = _payload()
        payload["ranked"][0]["adapter_name"] = (
            "\u200b" * 40 + "real-name")
        payload["ranked"][1]["adapter_name"] = (
            "bot \U0001f9d1\u200d\U0001f4bb pro")
        payload["unranked"][0]["adapter_name"] = "hid\u034fden"
        page = leaderboard_to_html(payload)
        self.assertIn("real-name", page)
        self.assertIn("\U0001f9d1\u200d\U0001f4bb", page)
        self.assertNotIn("\u034f", page)
        self.assertIn("hidden", page)

    def test_cost_tile_marks_flagged_co_carrier(self):
        # A flagged run sharing the top cost marks the top end
        # even when a ranked run listed first is the one named
        # there (pass 18).
        payload = _payload()
        payload["ranked"][0]["total_cost_usd"] = 9.0
        payload["unranked"][0].update({
            "total_cost_usd": 9.0, "asr_conditional": 0.30})
        page = leaderboard_to_html(payload)
        self.assertIn("TOP COST IS FLAGGED", page)

    def test_cost_tile_prints_subcent_spread(self):
        # A spread narrower than a cent prints at the precision
        # where its ends separate, through the separating
        # money formatter (pass 18).
        payload = _payload()
        payload["ranked"][0]["total_cost_usd"] = 0.001
        payload["ranked"][1]["total_cost_usd"] = 0.004
        page = leaderboard_to_html(payload)
        self.assertIn("$0.001", page)
        self.assertIn("$0.004", page)
        payload["ranked"][0]["total_cost_usd"] = 1234.5
        payload["ranked"][1]["total_cost_usd"] = 1234567.89
        page = leaderboard_to_html(payload)
        self.assertIn("$1,234,567.89", page)
        self.assertIn('class="kpi wide v', page)

    def test_retrieval_tile_marks_endpoints_and_counts(self):
        # A plain two-carrier range marks its flagged endpoint
        # and states how many models carry the family; an
        # all-flagged attributed range keeps its whole-set
        # mark (pass 18).
        payload = _payload()
        fam = {"family": "retrieval_poisoning", "asr": 0.50,
               "n_eligible": 400}
        payload["ranked"][0]["detail"] = {
            "families": {"retrieval_poisoning": fam},
            "calibration": {}}
        fam2 = {"family": "retrieval_poisoning", "asr": 0.80,
                "n_eligible": 400}
        payload["unranked"][0]["detail"] = {
            "families": {"retrieval_poisoning": fam2},
            "calibration": {}}
        page = leaderboard_to_html(payload)
        self.assertIn("HIGH END IS FLAGGED", page)
        self.assertIn("2 OF 3 MODELS", page)
        payload = _payload()
        base = payload["unranked"][0]
        rows = []
        for i, v in enumerate((0.10, 0.42, 0.50)):
            row = dict(base)
            row["adapter_name"] = f"flagged-{i}"
            row["detail"] = {
                "families": {"retrieval_poisoning": {
                    "family": "retrieval_poisoning", "asr": v,
                    "n_eligible": 400}},
                "calibration": {}}
            rows.append(row)
        payload["ranked"] = []
        payload["unranked"] = rows
        page = leaderboard_to_html(payload)
        self.assertIn("ALL CARRIERS FLAGGED", page)

    def test_retrieval_tile_counts_carrying_models_once(self):
        # The carry note counts models, as its word says: a
        # model carrying the family on both of its wires counts
        # once, against the field's distinct-model count. The
        # fixture is the live gpt-6-luna shape plus a carrying
        # model and a flagged non-carrier: four entries, three
        # models, two of the models carrying. Counted by entry
        # the note printed 3 OF 4 MODELS, a carrier count over
        # an entry count under a MODELS word. With one wire of
        # the pair dropped every model has one entry, and the
        # note prints exactly what the entry count printed.
        def row(name, version, asr, rp_asr=None):
            r = {
                "adapter_name": name,
                "adapter_version": version,
                "wire": name,
                "asr_conditional": asr,
                "asr_ci95": [asr - 0.02, asr + 0.02],
                "benign_accuracy": 0.97,
                "n_eligible": 400,
                "total_cost_usd": 1.0,
                "latency_ms_p50_attacked": 100.0,
                "ece_attacked": 0.05,
                "malformed_rate": 0.01,
            }
            if rp_asr is not None:
                r["detail"] = {
                    "families": {"retrieval_poisoning": {
                        "family": "retrieval_poisoning",
                        "asr": rp_asr, "n_eligible": 400}},
                    "calibration": {}}
            return r
        flagged = {"adapter_name": "broken-adapter",
                   "adapter_version": "flagged-model",
                   "wire": "broken-adapter",
                   "reason": "benign accuracy below ranking floor"}
        payload = {
            "ranked": [
                row("openai-structured", "gpt-6-luna", 0.12, 0.50),
                row("openai-decisions", "gpt-6-luna", 0.11, 0.80),
                row("other-adapter", "other-model", 0.20, 0.30),
            ],
            "unranked": [flagged],
        }
        page = leaderboard_to_html(payload)
        self.assertIn("2 OF 3 MODELS", page)
        self.assertNotIn("3 OF 4 MODELS", page)
        payload["ranked"] = payload["ranked"][1:]
        page = leaderboard_to_html(payload)
        self.assertIn("2 OF 3 MODELS", page)

    def test_models_tile_splits_an_all_flagged_field(self):
        payload = _payload()
        # The appended row is a second flagged model, so it
        # carries its own model ID: an exact copy would be the
        # same model-and-wire pair again, which the board holds
        # once, and the tile counts distinct models.
        second = dict(payload["unranked"][0])
        second["adapter_version"] = "0.2"
        payload["unranked"].append(second)
        payload["ranked"] = []
        page = leaderboard_to_html(payload)
        # Tile labels join with no-break entities in the HTML.
        self.assertIn("0 RANKED&nbsp;· 2 FLAGGED", page)

    def test_models_tile_counts_distinct_models_over_two_wires(self):
        # One model measured over two wires is two entries and
        # one model (Admission-Rules, Model identity). The tile
        # counts models: the headline is the number of distinct
        # model IDs, and the split classifies each model once,
        # so the split sums to the headline. Counted by entry
        # this fixture printed 4 models, 3 of them ranked.
        def row(name, version, asr):
            return {
                "adapter_name": name,
                "adapter_version": version,
                "wire": name,
                "asr_conditional": asr,
                "asr_ci95": [asr - 0.02, asr + 0.02],
                "benign_accuracy": 0.97,
                "n_eligible": 400,
                "total_cost_usd": 1.0,
                "latency_ms_p50_attacked": 100.0,
                "ece_attacked": 0.05,
                "malformed_rate": 0.01,
            }
        payload = {
            "ranked": [
                row("openai-structured", "gpt-6-luna", 0.12),
                row("openai-decisions", "gpt-6-luna", 0.11),
                row("other-adapter", "other-model", 0.20),
            ],
            "unranked": [
                {"adapter_name": "broken-adapter",
                 "adapter_version": "flagged-model",
                 "wire": "broken-adapter",
                 "reason": "benign accuracy below ranking floor"},
            ],
        }
        page = leaderboard_to_html(payload)
        self.assertIn(
            '<div class="kpi-num">3</div>'
            '<div class="kpi-lab">MODELS TESTED&nbsp;· '
            '2 RANKED&nbsp;· 1 FLAGGED</div>', page)
        # The same model over a ranked and an unranked wire is
        # a ranked model, never a flagged one: any ranked entry
        # ranks the model, and the model still counts once.
        # Counted by entry this form printed 3 models with 2
        # of them flagged.
        payload["ranked"] = [row("openai-structured",
                                 "gpt-6-luna", 0.12)]
        payload["unranked"].insert(0, {
            "adapter_name": "openai-decisions",
            "adapter_version": "gpt-6-luna",
            "wire": "openai-decisions",
            "reason": "malformed response rate above 5%",
            "malformed_rate": 0.09})
        page = leaderboard_to_html(payload)
        self.assertIn(
            '<div class="kpi-num">2</div>'
            '<div class="kpi-lab">MODELS TESTED&nbsp;· '
            '1 RANKED&nbsp;· 1 FLAGGED</div>', page)

    def test_lead_band_tile_counts_distinct_models(self):
        # The lead band tile states how many models stand tied
        # at the top, and the band holds entries: one model on
        # two wires holds two of its slots. The count is of
        # distinct model IDs, grouped by the same key the
        # MODELS TESTED tile counts by. Counted by entry this
        # fixture printed 4 models for a band of three.
        def row(name, version, asr):
            return {
                "adapter_name": name,
                "adapter_version": version,
                "display_name": version,
                "wire": name,
                "asr_conditional": asr,
                "asr_ci95": [asr - 0.02, asr + 0.02],
                "benign_accuracy": 0.97,
                "n_eligible": 400,
                "total_cost_usd": 1.0,
                "latency_ms_p50_attacked": 100.0,
                "ece_attacked": 0.05,
                "malformed_rate": 0.01,
            }
        payload = {
            "ranked": [
                row("openai-structured", "gpt-6-luna", 0.110),
                row("openai-decisions", "gpt-6-luna", 0.115),
                row("other-adapter", "other-model", 0.120),
                row("third-adapter", "third-model", 0.125),
            ],
            "unranked": [],
        }
        page = leaderboard_to_html(payload)
        self.assertIn(
            '<div class="kpi range"><div class="kpi-num">'
            '11.0–12.5%</div><div class="kpi-lab">LEAD BAND'
            '&nbsp;· 3 MODELS TIED AT THE TOP</div>', page)
        # When no model in the band repeats, the count is the
        # entry count it replaces: a band of three entries over
        # three models prints the same figure either way.
        payload["ranked"] = [
            row("openai-structured", "gpt-6-luna", 0.11),
            row("other-adapter", "other-model", 0.12),
            row("third-adapter", "third-model", 0.13),
        ]
        page = leaderboard_to_html(payload)
        self.assertIn(
            '<div class="kpi range"><div class="kpi-num">'
            '11.0–13.0%</div><div class="kpi-lab">LEAD BAND'
            '&nbsp;· 3 MODELS TIED AT THE TOP</div>', page)
        # A two-entry tie names both entries instead of
        # counting, and that form is unchanged when the two
        # entries are one model on two wires: the label names
        # the two measurements by the disambiguated names the
        # rest of the page uses, each traceable to its wire on
        # its card, and no count of models is stated at all.
        payload["ranked"] = [
            row("openai-structured", "gpt-6-luna", 0.110),
            row("openai-decisions", "gpt-6-luna", 0.115),
        ]
        page = leaderboard_to_html(payload)
        self.assertIn(
            '<div class="kpi range"><div class="kpi-num">'
            '11.0–11.5%</div><div class="kpi-lab">LEAD BAND'
            '&nbsp;· <span class="nbw">GPT-6-LUNA (1)</span>'
            ' AND <span class="nbw">GPT-6-LUNA (2)</span>'
            ' TIED</div>', page)
        self.assertNotIn("MODELS TIED AT THE TOP", page)

    def test_models_tile_counts_malformed_model_id_apart(self):
        # A malformed model ID (here a list in place of the
        # string) is an identity apart from the model its text
        # resembles: it neither merges with the lookalike
        # string model nor raises in the render. Two entries
        # carrying the same malformed ID are one such identity,
        # so this field of three entries counts two models.
        def row(name, version, display, asr):
            return {
                "adapter_name": name,
                "adapter_version": version,
                "display_name": display,
                "wire": name,
                "asr_conditional": asr,
                "asr_ci95": [asr - 0.02, asr + 0.02],
                "benign_accuracy": 0.97,
                "n_eligible": 400,
                "total_cost_usd": 1.0,
                "latency_ms_p50_attacked": 100.0,
                "ece_attacked": 0.05,
                "malformed_rate": 0.01,
            }
        payload = {
            "ranked": [
                row("weird-adapter", ["kimi-k3"], "weird-model",
                    0.30),
                row("other-wire", ["kimi-k3"], "weird-model",
                    0.32),
                row("moonshot", "kimi-k3", "kimi-k3", 0.31),
            ],
            "unranked": [],
        }
        page = leaderboard_to_html(payload)
        self.assertIn(
            '<div class="kpi-num">2</div>'
            '<div class="kpi-lab">MODELS TESTED</div>', page)

    def test_scatter_coincident_points_offset_and_disclosed(self):
        # Two runs at one cost and rate both stay visible, and
        # the chart's description discloses the offset; axis
        # ticks group like money (pass 18).
        payload = _payload()
        payload["ranked"][1]["total_cost_usd"] = 1.23
        payload["ranked"][1]["asr_conditional"] = 0.20
        payload["ranked"][1]["asr_ci95"] = [0.15, 0.26]
        page = leaderboard_to_html(payload)
        start = page.index('class="chart scatter-d"')
        start = page.rindex("<svg", 0, start)
        svg = page[start:page.index("</svg>", start)]
        cxs = re.findall(r'class="pt" cx="([\d.]+)"', svg)
        self.assertGreater(len(set(cxs)), 1)
        # The offset is capped at a marker width and the
        # description says so in those terms (pass 23): the
        # uncapped search could park a point where the axis
        # reads multiples of its true cost while disclosing
        # only "offset slightly".
        self.assertIn(
            "offset by a marker width at most so each stays "
            "visible", svg)
        self.assertIn(
            "crowded points are offset by a marker width at "
            "most", svg)
        payload["ranked"][0]["total_cost_usd"] = 2000000.0
        page = leaderboard_to_html(payload)
        self.assertIn("$1M", page)
        self.assertNotIn("$1e+06", page)

    def test_scatter_legend_draws_below_the_points(self):
        page = leaderboard_to_html(_payload())
        for marker in ('class="chart scatter-d"',
                       'class="chart scatter-m"'):
            start = page.index(marker)
            start = page.rindex("<svg", 0, start)
            svg = page[start:page.index("</svg>", start)]
            self.assertLess(
                svg.index('stroke="#3a4652" stroke-width="1"'),
                svg.index('<circle class="pt"'))

    def test_asr_less_ranked_row_has_no_strip_rank_speech(self):
        # A ranked row with no ASR keeps no rank speech on the
        # strip surfaces, in either form (pass 18).
        payload = _payload()
        del payload["ranked"][1]["asr_conditional"]
        payload["ranked"][1]["malformed_rate"] = 0.03
        payload["ranked"][0]["malformed_rate"] = 0.02
        page = leaderboard_to_html(payload)
        start = page.index('class="chart strip-chart"')
        start = page.rindex("<svg", 0, start)
        svg = page[start:page.index("</svg>", start)]
        self.assertIn("no ASR recorded", svg)
        self.assertNotIn(", rank 2", svg)
        mstart = page.index('class="malformed-mobile"')
        self.assertNotIn("rank 2 of", page[mstart:])

    def test_rounded_negative_zero_prints_unsigned(self):
        # A value that merely rounds to zero drops its sign in
        # the printed figure (pass 18).
        payload = _payload()
        payload["ranked"][0]["malformed_rate"] = -0.00001
        payload["ranked"][1]["malformed_rate"] = 0.02
        page = leaderboard_to_html(payload)
        self.assertNotIn("-0.0%", page)

    def test_heat_cells_carry_text_not_tooltips(self):
        # A heat cell's exact text always leads its content,
        # base or no base, and no cell carries a tooltip title
        # (pass 18).
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {
                "canary_leakage": {
                    "family": "canary_leakage", "asr": 0.05},
            },
            "calibration": {},
        }
        page = leaderboard_to_html(payload)
        self.assertIn(
            '<span class="sr-only">canary leakage 5.0%</span>',
            page)
        for tm in re.finditer(r"<table\b.*?</table>", page,
                              flags=re.S):
            self.assertNotIn('title="', tm.group(0))

    def test_landmarks_are_named_by_their_headings(self):
        page = leaderboard_to_html(_payload())
        self.assertIn('aria-labelledby="h2-ranking"', page)
        self.assertIn('<h2 id="h2-ranking">', page)
        self.assertNotIn('aria-label="Model ranking"', page)
        self.assertIn('aria-labelledby="h2-notes"', page)

    def test_hero_annotation_fits_inside_the_panel(self):
        # An annotation starting near the scale top is clamped
        # so its whole text stays inside the viewBox (pass 18).
        payload = _payload()
        payload["ranked"][0].update({
            "asr_conditional": 0.29, "asr_ci95": [0.27, 0.30],
            "malformed_rate": 0.01})
        payload["ranked"][1].update({
            "asr_conditional": 0.295, "asr_ci95": [0.28, 0.30],
            "malformed_rate": 0.02})
        page = leaderboard_to_html(payload)
        svg = _hero_svg(page)
        for m in re.finditer(
                r'<text x="([\d.]+)"[^>]*class="h-malf[^"]*"[^>]*>'
                r"([^<]+)</text>", svg):
            self.assertLessEqual(
                float(m.group(1)) + 7.3 * len(m.group(2)), 1226)

    def test_phone_hero_names_never_ellipsise(self):
        page = leaderboard_to_html(_payload())
        self.assertNotIn("text-overflow:ellipsis", page)

    def test_family_impostor_takes_a_suffix(self):
        # A doubled-underscore key must not pass itself off as
        # the retrieval family in prose on any surface: both
        # colliding names take position suffixes (pass 18).
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {
                "retrieval_poisoning": {
                    "family": "retrieval_poisoning", "asr": 0.5,
                    "n_eligible": 400},
                "retrieval__poisoning": {
                    "family": "retrieval__poisoning", "asr": 0.6,
                    "n_eligible": 400},
            },
            "calibration": {}}
        page = leaderboard_to_html(payload)
        self.assertEqual(
            page.count(">retrieval poisoning (1)</th>"), 2)
        self.assertEqual(
            page.count(">retrieval poisoning (2)</th>"), 2)
        self.assertNotIn(">retrieval poisoning</th>", page)

    def test_hatch_pattern_paints_both_tile_edges(self):
        # The desktop hatch stripe sits on both tile edges so
        # the painted duty matches the phone form's roughly one
        # third amber; a lone centred stripe paints half its
        # width (pass 17).
        page = leaderboard_to_html(_payload())
        self.assertIn(
            '<pattern id="hatch" width="7" height="7"', page)
        self.assertIn(
            '<line x1="7" y1="0" x2="7" y2="7" '
            'stroke="#e8a33d" stroke-width="2.4"/>', page)

    # ------------------------------------------------ pass 22
    # The pass-19 red team's full report reached adjudication
    # in pass 22; these pins cover its sustained items.

    def test_gate_edge_one_digit_deeper(self):
        # Rates a hair either side of the gate rounded to the
        # same two-decimal figure pass 18 printed, so the
        # precision rule chases the edge: 0.05004 and 0.04996
        # print at three decimals with their opposite
        # verdicts legible (pass 22).
        payload = _payload()
        payload["ranked"][0]["malformed_rate"] = 0.05004
        payload["ranked"][1]["malformed_rate"] = 0.04996
        page = leaderboard_to_html(payload)
        self.assertIn("5.004%", page)
        self.assertIn("4.996%", page)
        self.assertIn("Malformed response rate above 5%", page)
        self.assertIn(
            "Malformed response rate at or under 5%", page)

    def test_share_edges_one_digit_deeper(self):
        # Calibration shares a hair off completeness or
        # emptiness print at the precision where the hair
        # shows, not the two decimals that still read as the
        # edge (pass 22).
        payload = _payload()
        payload["ranked"][0]["n_eligible"] = 25000
        payload["ranked"][0]["detail"] = {
            "families": {},
            "calibration": {"attacked": {"n": 24999}},
        }
        payload["ranked"][1]["n_eligible"] = 25000
        payload["ranked"][1]["detail"] = {
            "families": {},
            "calibration": {"attacked": {"n": 1}},
        }
        page = leaderboard_to_html(payload)
        self.assertIn("24,999 · 99.996%", page)
        self.assertIn("1 · 0.004%", page)

    def test_suffix_namespace_is_reserved_for_models(self):
        # A name that literally ends in a suffix the collision
        # rule hands out keeps the suffix space from being
        # reused: the colliding pair moves past it instead of
        # printing one name for two models (pass 22).
        payload = _payload()
        payload["ranked"] = [
            {"adapter_name": "aaa", "display_name": "model-x",
             "asr_conditional": 0.10, "asr_ci95": [0.08, 0.12],
             "benign_accuracy": 0.9, "n_eligible": 400,
             "ece_attacked": 0.05},
            {"adapter_name": "bbb", "display_name": "model-x",
             "asr_conditional": 0.20, "asr_ci95": [0.18, 0.22],
             "benign_accuracy": 0.9, "n_eligible": 400,
             "ece_attacked": 0.05},
            {"adapter_name": "ccc", "display_name": "model-x (1)",
             "asr_conditional": 0.30, "asr_ci95": [0.28, 0.32],
             "benign_accuracy": 0.9, "n_eligible": 400,
             "ece_attacked": 0.05},
        ]
        payload["unranked"] = []
        page = leaderboard_to_html(payload)
        hero = _hero_svg(page)
        for form in ("model-x (1)", "model-x (2)", "model-x (3)"):
            self.assertIn(form, hero)

    def test_suffix_namespace_is_reserved_for_families(self):
        # The family analogue: a literal a_b_(1) in the data
        # reserves its printed form, so the a_b and a__b
        # collision takes the next suffix, not the squatter's
        # (pass 22).
        payload = _payload()
        fams = {"a_b": {"asr": 0.10, "n": 400},
                "a__b": {"asr": 0.20, "n": 400},
                "a_b_(1)": {"asr": 0.30, "n": 400}}
        payload["ranked"][0]["detail"] = {
            "families": fams, "calibration": {}}
        page = leaderboard_to_html(payload)
        self.assertIn(">a b (1)</th>", page)
        self.assertIn(">a b (2)</th>", page)
        self.assertIn(">a b (3)</th>", page)

    def test_scatter_solved_label_yields_to_a_point(self):
        # The hand-placed label for kimi-k3 ends left of its
        # point; a decoy point inside that box makes the
        # placement name the wrong point, so the label moves
        # and the decoy's centre stays outside its box
        # (pass 22).
        def row(name, asr, cost):
            return {"adapter_name": name, "display_name": name,
                    "asr_conditional": asr,
                    "asr_ci95": [asr - 0.01, asr + 0.01],
                    "benign_accuracy": 0.9, "n_eligible": 400,
                    "total_cost_usd": cost, "ece_attacked": 0.05,
                    "malformed_rate": 0.01}

        payload = {"ranked": [
            row("anchor-lo", 0.30, 0.20),
            row("anchor-hi", 0.28, 100.0),
            row("kimi-k3", 0.11, 21.02),
            row("decoy-mid", 0.1137, 12.22),
        ], "unranked": []}
        page = leaderboard_to_html(payload)
        i = page.find('class="chart scatter-d"')
        svg = page[page.rindex("<svg", 0, i):
                   page.index("</svg>", i)]
        centres = {(round(float(a), 1), round(float(b), 1))
                   for a, b in re.findall(
                       r'<circle class="pt" cx="([\d.]+)" '
                       r'cy="([\d.]+)"', svg)}
        decoy = [c for c in centres
                 if abs(c[0] - 389.9) < 6 and abs(c[1] - 230) < 6]
        self.assertEqual(len(decoy), 1)
        lab = re.search(
            r'<text x="([\d.]+)" y="([\d.]+)" class="s-lab" '
            r'[^>]*text-anchor="(\w+)"[^>]*>kimi-k3</text>', svg)
        self.assertIsNotNone(lab)
        x, y, anch = (float(lab.group(1)), float(lab.group(2)),
                      lab.group(3))
        w = len("kimi-k3") * 7.0
        x0 = x - w if anch == "end" else x
        dx, dy = decoy[0]
        self.assertFalse(
            x0 <= dx <= x0 + w and y - 11.5 <= dy <= y,
            "kimi-k3 label box still covers the decoy point")

    def test_scatter_near_coincident_points_are_disclosed(self):
        # Two points a disc-width apart merged into one glyph
        # with no disclosure under the exact-equality rule;
        # the offset now fires on clearance and the
        # description says so (pass 22).
        def row(name, asr, cost):
            return {"adapter_name": name, "display_name": name,
                    "asr_conditional": asr,
                    "asr_ci95": [asr - 0.01, asr + 0.01],
                    "benign_accuracy": 0.9, "n_eligible": 400,
                    "total_cost_usd": cost, "ece_attacked": 0.05,
                    "malformed_rate": 0.01}

        payload = {"ranked": [
            row("anchor-lo", 0.30, 0.20),
            row("anchor-hi", 0.28, 100.0),
            row("kimi-k3", 0.11, 21.02),
            row("decoy-mid", 0.113, 18.45),
        ], "unranked": []}
        page = leaderboard_to_html(payload)
        self.assertIn(
            "or too near to draw apart, are offset by a "
            "marker width at most",
            page)

    def test_scatter_nudge_never_lands_on_a_third_point(self):
        # The blind single step moved a coincident point onto
        # a third point sitting at the step's destination;
        # the destination is checked now, so every centre
        # keeps a disc diameter from every other (pass 22).
        def row(name, asr, cost):
            return {"adapter_name": name, "display_name": name,
                    "asr_conditional": asr,
                    "asr_ci95": [asr - 0.01, asr + 0.01],
                    "benign_accuracy": 0.9, "n_eligible": 400,
                    "total_cost_usd": cost, "ece_attacked": 0.05,
                    "malformed_rate": 0.01}

        payload = {"ranked": [
            row("anchor-lo", 0.30, 0.20),
            row("anchor-hi", 0.28, 100.0),
            row("p-three", 0.149, 24.16),
            row("p-one", 0.15, 30.0),
            row("p-two", 0.15, 30.0),
        ], "unranked": []}
        page = leaderboard_to_html(payload)
        i = page.find('class="chart scatter-d"')
        svg = page[page.rindex("<svg", 0, i):
                   page.index("</svg>", i)]
        centres = sorted({(round(float(a), 1), round(float(b), 1))
                          for a, b in re.findall(
                              r'<circle class="pt" cx="([\d.]+)" '
                              r'cy="([\d.]+)"', svg)})
        self.assertEqual(len(centres), 5)
        for j, (ax, ay) in enumerate(centres):
            for bx, by in centres[j + 1:]:
                self.assertGreaterEqual(
                    ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5,
                    11.9)

    def test_hero_annotation_clears_the_value(self):
        # At the scale top the annotation's edge clamp pulled
        # it back onto the row's own value text on the same
        # baseline; the two spans never intersect now
        # (pass 22).
        payload = _payload()
        payload["ranked"] = [{
            "adapter_name": "top-a", "display_name": "top-a",
            "asr_conditional": 0.995, "asr_ci95": [0.99, 0.999],
            "benign_accuracy": 0.99, "n_eligible": 400,
            "ece_attacked": 0.05, "malformed_rate": 0.01,
        }]
        payload["unranked"] = []
        page = leaderboard_to_html(payload)
        hero = _hero_svg(page)
        val = re.search(
            r'<text x="([\d.]+)" y="([\d.]+)" class="h-val">'
            r"([^<]*)</text>", hero)
        ann = re.search(
            r'<text x="([\d.]+)" y="([\d.]+)" class="h-malf[^"]*"'
            r"[^>]*>([^<]*)</text>", hero)
        self.assertIsNotNone(val)
        self.assertIsNotNone(ann)
        vx, ax = float(val.group(1)), float(ann.group(1))
        vend = vx + len(val.group(3)) * 9.0
        aend = ax + len(ann.group(3)) * 7.3
        self.assertTrue(
            aend <= vx or vend <= ax,
            "hero annotation span intersects the value span")

    def test_rank_denominators_count_ranked_with_asr(self):
        # An asr-less ranked row holds no rank on any surface,
        # so the caption and the chips count it out. The pass
        # 22 form of this test let the models tile keep the
        # admission count under the same word; three panels
        # refiled the two counts (passes 26, 27 and 30), and
        # the tile now counts the same population as the
        # chips and states the asr-less run as its own line
        # of the split (reconciliation ledger, two-counts).
        payload = _payload()
        payload["ranked"][1] = {
            "adapter_name": "ghost", "display_name": "ghost",
            "benign_accuracy": 0.9, "n_eligible": 400,
            "ece_attacked": 0.05}
        payload["unranked"][0].update({
            "asr_conditional": 0.25, "asr_ci95": [0.23, 0.27],
            "malformed_rate": 0.10})
        page = leaderboard_to_html(payload)
        self.assertIn("ranks count the 1 ranked model only",
                      page)
        self.assertIn("RANK 1 OF 1 RANKED", page)
        self.assertIn("1 RANKED&nbsp;· 1 RANKED WITHOUT A "
                      "RECORDED ASR&nbsp;· 1 FLAGGED", page)

    def test_spark_caption_judges_the_printed_twenty(self):
        # A family at 0.1996 prints 20.0 percent on the card,
        # so the caption names it as the top spike instead of
        # claiming no family reaches 20 percent (pass 22).
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {
                "retrieval_poisoning": {"asr": 0.50, "n": 400},
                "verbosity": {"asr": 0.1996, "n": 400}},
            "calibration": {}}
        page = leaderboard_to_html(payload)
        self.assertIn("top other spike is", page)
        self.assertIn("verbosity 20.0%", page)
        self.assertNotIn("no other family reaches 20%", page)

    def test_single_value_tiles_count_flagged_carriers(self):
        # One figure carried by a ranked and a flagged run
        # belongs to neither status alone: both single-value
        # tiles count their flagged carriers instead of
        # stating the flagged status for the shared figure
        # (pass 22).
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {
                "retrieval_poisoning": {"asr": 0.50, "n": 400}},
            "calibration": {}}
        payload["ranked"][0]["total_cost_usd"] = 5.0
        payload["ranked"][1]["total_cost_usd"] = 5.0
        payload["unranked"][0].update({
            "total_cost_usd": 5.0,
            "detail": {"families": {
                "retrieval_poisoning": {"asr": 0.50, "n": 400}},
                "calibration": {}}})
        page = leaderboard_to_html(payload)
        self.assertIn("1 OF 2 CARRIERS FLAGGED", page)
        self.assertIn("1 OF 3 CARRIERS FLAGGED", page)
        self.assertNotIn(
            "RETRIEVAL POISONING ASR · FLAGGED", page)

    def test_single_value_all_flagged_keeps_its_mark(self):
        # When every carrier of the shared figure is flagged,
        # the plain flagged mark stands (pass 22).
        payload = _payload()
        for row in payload["ranked"]:
            row.pop("detail", None)
        payload["unranked"] = [
            {"adapter_name": "flag-a", "display_name": "flag-a",
             "reason": "benign accuracy below ranking floor",
             "detail": {"families": {
                 "retrieval_poisoning": {"asr": 0.50, "n": 400}},
                 "calibration": {}}},
            {"adapter_name": "flag-b", "display_name": "flag-b",
             "reason": "benign accuracy below ranking floor",
             "detail": {"families": {
                 "retrieval_poisoning": {"asr": 0.50, "n": 400}},
                 "calibration": {}}},
        ]
        page = leaderboard_to_html(payload)
        self.assertIn("FLAGGED&nbsp;· NO&nbsp;RANK", page)

    def test_gate_claim_in_synonym_words(self):
        # A gate claim phrased without the word malformed is
        # still a gate claim: the note derives from the value
        # and the claim does not print above a MALFORMED stat
        # that contradicts it (pass 22).
        payload = _payload()
        payload["unranked"][0].update({
            "reason": "ranking-ineligible: "
                      "response_format_rate above 5%",
            "malformed_rate": 0.03,
        })
        page = leaderboard_to_html(payload)
        self.assertIn(
            "Malformed response rate at or under 5%", page)
        self.assertNotIn("Response format rate above 5%", page)

    def test_subcent_costs_print_their_figure(self):
        # A positive sub-cent cost never prints as zero on
        # any surface, and a spread's ends print at the
        # precision where they separate (pass 22).
        payload = _payload()
        payload["ranked"] = [{
            "adapter_name": "cheap", "display_name": "cheap",
            "asr_conditional": 0.20, "asr_ci95": [0.15, 0.26],
            "benign_accuracy": 0.9, "n_eligible": 400,
            "total_cost_usd": 0.00049, "ece_attacked": 0.05,
        }]
        payload["unranked"] = []
        page = leaderboard_to_html(payload)
        self.assertIn("$0.0005", page)
        self.assertNotIn("$0.000<", page)
        payload["ranked"][0]["total_cost_usd"] = 0.0049
        page = leaderboard_to_html(payload)
        self.assertIn("$0.005", page)
        payload["ranked"] = [
            {"adapter_name": "c-one", "display_name": "c-one",
             "asr_conditional": 0.20, "asr_ci95": [0.15, 0.26],
             "benign_accuracy": 0.9, "n_eligible": 400,
             "total_cost_usd": 0.1234561, "ece_attacked": 0.05},
            {"adapter_name": "c-two", "display_name": "c-two",
             "asr_conditional": 0.30, "asr_ci95": [0.25, 0.36],
             "benign_accuracy": 0.9, "n_eligible": 400,
             "total_cost_usd": 0.1234564, "ece_attacked": 0.05},
        ]
        page = leaderboard_to_html(payload)
        self.assertIn("$0.1234561", page)
        self.assertIn("$0.1234564", page)

    def test_footer_names_every_tied_benchmark_holder(self):
        # Two runs tied on benign accuracy both set that
        # benchmark, and the footer names both instead of
        # assigning the status to the first listed (pass 22).
        payload = _payload()
        payload["ranked"][0].update({
            "display_name": "zeta", "benign_accuracy": 0.99,
            "ece_attacked": 0.05})
        payload["ranked"][1].update({
            "display_name": "alpha", "benign_accuracy": 0.99,
            "ece_attacked": 0.06})
        page = leaderboard_to_html(payload)
        self.assertIn(
            "zeta and alpha at 99.0% for benign accuracy",
            page)

    def test_footer_benchmark_sentence_survives_without_ece(self):
        # With no ECE anywhere the benign benchmark sentence
        # still prints, so the benchmark the card tax labels
        # invoke exists on the page (pass 22).
        payload = _payload()
        for row in payload["ranked"]:
            row.pop("ece_attacked", None)
        page = leaderboard_to_html(payload)
        self.assertIn(
            "the benign benchmark is the best ranked run",
            page)

    def test_footer_each_flips_for_a_countless_card(self):
        # A card whose calibration block carries scores but
        # no count prints CALIB N n/a, and the footer's
        # universal share claim flips to "a" for it too
        # (pass 22).
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {},
            "calibration": {"attacked": {"ece": 0.05,
                                         "brier": 0.10}},
        }
        payload["ranked"][1]["detail"] = {
            "families": {},
            "calibration": {"attacked": {"n": 400}},
        }
        page = leaderboard_to_html(payload)
        self.assertIn("The share beside a calibration count",
                      page)
        self.assertNotIn("beside each calibration count",
                         page)

    def test_tile_names_keep_the_models_spelling(self):
        # Tile labels uppercase ASCII only: a name whose
        # letters expand under Unicode uppercasing keeps the
        # spelling every other surface prints (pass 22).
        payload = _payload()
        payload["ranked"][0]["display_name"] = "straße-x"
        page = leaderboard_to_html(payload)
        self.assertIn("STRAßE-X", page)
        self.assertNotIn("STRASSE-X", page)

    def test_benign_edge_prints_share_precision(self):
        # A benign accuracy a hair under perfect prints the
        # hair, not the perfect score the one-decimal form
        # claimed with no checkable base (pass 22).
        payload = _payload()
        payload["ranked"][0]["benign_accuracy"] = 0.9996
        page = leaderboard_to_html(payload)
        self.assertIn("99.96%", page)

    def test_braille_blank_names_collide(self):
        # The braille blank renders as space but is not
        # whitespace to the collision norm; stripped in
        # cleaning, the two names collide and suffix like
        # any other collision (pass 22).
        payload = _payload()
        payload["ranked"][0]["display_name"] = "a\u2800b"
        payload["ranked"][1]["display_name"] = "ab"
        page = leaderboard_to_html(payload)
        self.assertIn("ab (1)", page)
        self.assertIn("ab (2)", page)

    def test_phone_heat_caption_states_the_carrier_base(self):
        # The visible small-screen caption states that the
        # family averages run over the models carrying each
        # family, not only the screen-reader caption
        # (pass 22). Since pass 38 the statement rides in
        # the panel's own reading line's phone span, the
        # caption's small-screens span retired; it stays
        # visible at small screens, inside the panel.
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {
                "verbosity": {"asr": 0.30, "n": 400}},
            "calibration": {}}
        page = leaderboard_to_html(payload)
        self.assertIn(
            "average attack success over the models carrying "
            "each family", page)

    def test_derived_figures_disclosed_as_unrounded(self):
        # The footer states that derived figures are computed
        # from unrounded values, so a recomputation from the
        # printed roundings that differs in the last place
        # does not read as an error (pass 22).
        page = leaderboard_to_html(_payload())
        self.assertIn(
            "Derived figures are computed from the unrounded "
            "values", page)

    # --------------------------------------- pass 22, batch 2
    # The pass-22 panels' own sustained items, plus the
    # pass-20 viz V1 and pass-19 copy C1 items that reached
    # adjudication in this pass.

    def test_strip_gate_line_paints_behind_the_values(self):
        # The admission line and its underlay are emitted
        # before every value label, so a label the line
        # crosses is knocked out by its own halo instead of
        # being struck through at its decimal point
        # (pass 20 viz V1, fixed in pass 22).
        payload = _payload()
        payload["ranked"][0]["malformed_rate"] = 0.042
        payload["ranked"][1]["malformed_rate"] = 0.10
        payload["unranked"][0]["malformed_rate"] = 0.073
        page = leaderboard_to_html(payload)
        i = page.find('class="chart strip-chart"')
        svg = page[page.rindex("<svg", 0, i):
                   page.index("</svg>", i)]
        gate = svg.find('stroke-dasharray="4 3"')
        self.assertGreater(gate, 0)
        self.assertLess(gate, svg.find('class="m-val'))
        self.assertLess(gate, svg.rfind('class="m-val'))

    def test_lead_tile_names_a_flagged_contender(self):
        # A flagged run at or inside the lead's rates is
        # named on the lead tile with its figure and flag:
        # dropped in silence, the tile stated a superlative
        # the field does not hold (pass 22 red team).
        payload = _payload()
        payload["ranked"] = [{
            "adapter_name": "alpha", "display_name": "alpha",
            "asr_conditional": 0.20, "asr_ci95": [0.19, 0.21],
            "benign_accuracy": 0.9, "n_eligible": 400,
            "total_cost_usd": 5.0, "ece_attacked": 0.05,
            "malformed_rate": 0.01}]
        payload["unranked"] = [{
            "adapter_name": "beta", "display_name": "beta",
            "asr_conditional": 0.05, "asr_ci95": [0.04, 0.06],
            "benign_accuracy": 0.9, "n_eligible": 400,
            "total_cost_usd": 1.0, "ece_attacked": 0.05,
            "malformed_rate": 0.10,
            "reason": "ranking-ineligible: "
                      "malformed_rate above 5%"}]
        page = leaderboard_to_html(payload)
        self.assertIn(
            "LOWEST ASR&nbsp;· "
            '<span class="nbw">ALPHA</span>&nbsp;· FLAGGED '
            '<span class="nbw">BETA</span> AT 5.0%', page)

    def test_lead_band_tile_names_a_flagged_contender(self):
        # The band form of the same rule: a flagged run
        # sitting between the tied pair at the top is named
        # on the tile, not silently excluded from the band
        # a reader takes as the top group (pass 22).
        payload = _payload()
        payload["ranked"] = [
            {"adapter_name": "alpha", "display_name": "alpha",
             "asr_conditional": 0.10, "asr_ci95": [0.09, 0.115],
             "benign_accuracy": 0.9, "n_eligible": 400,
             "ece_attacked": 0.05, "malformed_rate": 0.01},
            {"adapter_name": "gamma", "display_name": "gamma",
             "asr_conditional": 0.11, "asr_ci95": [0.095, 0.12],
             "benign_accuracy": 0.9, "n_eligible": 400,
             "ece_attacked": 0.05, "malformed_rate": 0.01}]
        payload["unranked"] = [{
            "adapter_name": "beta", "display_name": "beta",
            "asr_conditional": 0.105, "asr_ci95": [0.09, 0.12],
            "benign_accuracy": 0.9, "n_eligible": 400,
            "ece_attacked": 0.05, "malformed_rate": 0.10,
            "reason": "ranking-ineligible: "
                      "malformed_rate above 5%"}]
        page = leaderboard_to_html(payload)
        self.assertIn(
            "LEAD BAND&nbsp;· "
            '<span class="nbw">ALPHA</span> AND '
            '<span class="nbw">GAMMA</span> TIED&nbsp;· '
            'FLAGGED <span class="nbw">BETA</span> AT 10.5%',
            page)

    def test_base_ranges_scope_to_the_recorders(self):
        # A cell or model with no recorded base takes the
        # universal phrasing with it: the heat caption and
        # the KPI note scope their ranges to the cells and
        # models that record one (pass 22 red team).
        payload = _payload()
        fam = {"retrieval_poisoning": {"asr": 0.827,
                                       "n_eligible": 400},
               "verbosity": {"asr": 0.30, "n_eligible": 358}}
        payload["ranked"][0]["detail"] = {
            "families": fam, "calibration": {}}
        payload["ranked"][1]["detail"] = {
            "families": {
                "retrieval_poisoning": {"asr": 0.50},
                "verbosity": {"asr": 0.20, "n_eligible": 470}},
            "calibration": {}}
        page = leaderboard_to_html(payload)
        # Sentence case since pass 38, when the clause
        # became the heat caption's lead (and only) line.
        self.assertIn(
            "Cells with a recorded base rest on 358 to 470 "
            "eligible cases", page)
        self.assertIn(
            "family bases 358 to 470 over the cells that "
            "record one", page)
        self.assertNotIn("each cell rests on", page)
        # And with a ranked model recording no headline base,
        # the note scopes that range too, in the singular.
        payload2 = _payload()
        payload2["ranked"][0]["n_eligible"] = 4591
        payload2["ranked"][0]["detail"] = {
            "families": fam, "calibration": {}}
        payload2["ranked"][1].pop("n_eligible")
        payload2["ranked"][1]["detail"] = {
            "families": fam, "calibration": {}}
        page2 = leaderboard_to_html(payload2)
        self.assertIn(
            "headline bases 4,591 to 4,591 over the 1 model "
            "that records one", page2)

    def test_severity_yardstick_scopes_to_interval_blocks(self):
        # A severity rate printed with no interval is not
        # covered by the caption's widest-reach figure, and
        # the caption says so instead of claiming the
        # page's widest over blocks it never measured
        # (pass 22 red team).
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {}, "calibration": {},
            "severities": {
                "critical": {"flip_rate_raw": 0.90,
                             "n_eligible": 10},
                "high": {"flip_rate_raw": 0.50,
                         "n_eligible": 10},
                "medium": {"flip_rate_raw": 0.10,
                           "n_eligible": 10}}}
        payload["ranked"][1]["detail"] = {
            "families": {}, "calibration": {},
            "severities": {
                "critical": {"flip_rate_raw": 0.20,
                             "n_eligible": 400,
                             "flip_rate_ci95": [0.18, 0.22]},
                "high": {"flip_rate_raw": 0.10,
                         "n_eligible": 400,
                         "flip_rate_ci95": [0.09, 0.11]},
                "medium": {"flip_rate_raw": 0.05,
                           "n_eligible": 400,
                           "flip_rate_ci95": [0.04, 0.06]}}}
        page = leaderboard_to_html(payload)
        self.assertIn("at the widest", page)
        self.assertIn(
            "rates shown without an interval carry no such "
            "bound", page)

    def test_spark_fill_claim_carries_its_exception(self):
        # The fill clause names its one exception in the
        # clause itself: the retrieval bar's fill is orange
        # on ranked and flagged cards alike, so the colour
        # rule a hurried reader takes from the first clause
        # is the rule the cards actually follow (pass 19
        # copy C1, fixed in pass 22).
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {
                "retrieval_poisoning": {"asr": 0.50, "n": 400}},
            "calibration": {}}
        page = leaderboard_to_html(payload)
        self.assertIn(
            "grey on flagged cards, apart from the orange "
            "retrieval spike", page)

    def test_nav_landmark_carries_a_name(self):
        # The module nav is a landmark, and it carries an
        # accessible name like every other landmark on the
        # page (pass 22 a11y).
        page = leaderboard_to_html(_payload())
        self.assertIn(
            '<nav class="modnav" aria-label="Page sections">',
            page)

    # ------------------------------------------------ pass 23

    def test_invisible_display_name_falls_back(self):
        # A display name of invisible characters only is
        # truthy as stored, and testing it before cleaning
        # blanked every surface while the usable adapter
        # name appeared nowhere; the fallback engages on
        # the cleaned name (contract F1).
        payload = _payload()
        payload["ranked"][0]["display_name"] = "\u200b\u200b"
        page = leaderboard_to_html(payload)
        self.assertIn("shieldstral-1.0", page)
        payload["ranked"][0]["display_name"] = "   "
        page = leaderboard_to_html(payload)
        self.assertIn("shieldstral-1.0", page)

    def test_family_variant_alone_is_the_family(self):
        # A sole family key differing from a known family
        # only in case or underscores is that family, tile,
        # hot column and orange spark included; the
        # both-present impostor shape stays suffixed (the
        # pass 18 pin above), so canonicalisation applies
        # only to a sole claimant (contract F4).
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {
                "Retrieval_Poisoning": {
                    "family": "Retrieval_Poisoning",
                    "asr": 0.5, "n_eligible": 400}},
            "calibration": {}}
        page = leaderboard_to_html(payload)
        self.assertIn("RETRIEVAL POISONING", page)
        self.assertIn('class="spark hot"', page)
        self.assertNotIn("Retrieval Poisoning", page)

    def test_invisible_family_prints_a_placeholder(self):
        # A family key of invisible characters only printed
        # as a blank header, a blank spark title and an
        # empty entry in the cards caption's list; it takes
        # the placeholder instead (contract F3).
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {
                "\u200b\u200b": {"family": "\u200b\u200b",
                                 "asr": 0.5, "n_eligible": 400}},
            "calibration": {}}
        page = leaderboard_to_html(payload)
        self.assertIn("unnamed family", page)

    def test_reason_with_the_word_malformed_prints_verbatim(self):
        # The gate-note swap triggers on a threshold claim,
        # not the bare word: a reason merely mentioning
        # malformed prints as recorded (contract F5, the
        # unpinned half of pass 19 contract F4).
        payload = _payload()
        payload["unranked"][0]["reason"] = (
            "malformed data breach, duplicate run")
        payload["unranked"][0]["malformed_rate"] = 0.119
        page = leaderboard_to_html(payload)
        self.assertIn("malformed data breach, duplicate run",
                      page)

    def test_gate_reason_without_a_value_prints_the_reason(self):
        # A gate claim with no malformed value recorded
        # deleted the recorded reason outright; with
        # nothing on the card for the claim to contradict,
        # the reason prints as recorded (contract F5).
        payload = _payload()
        payload["unranked"][0]["reason"] = (
            "ranking-ineligible: malformed_rate above 5%")
        page = leaderboard_to_html(payload)
        self.assertIn("Malformed response rate above 5%", page)
        self.assertNotIn("No reason recorded", page)

    def test_flagged_card_without_a_reason_says_so(self):
        # The humaniser's fallback was unreachable for a
        # missing reason, which printed an empty note; the
        # absence is itself the record (contract F5).
        payload = _payload()
        del payload["unranked"][0]["reason"]
        page = leaderboard_to_html(payload)
        self.assertIn("No reason recorded", page)

    def test_nonstring_reason_prints_no_repr(self):
        # A list reason printed as a Python repr; non-scalar
        # reasons take the recorded-absence line instead
        # (contract F8).
        payload = _payload()
        payload["unranked"][0]["reason"] = ["evil", "list"]
        page = leaderboard_to_html(payload)
        self.assertNotIn("['evil', 'list']", page)
        self.assertIn("No reason recorded", page)

    def test_reason_url_survives_verbatim(self):
        # The underscore transform used to rewrite a URL
        # inside a prose reason into a different string
        # (contract F8).
        payload = _payload()
        payload["unranked"][0]["reason"] = (
            "see https://example.com/x_y for the log")
        page = leaderboard_to_html(payload)
        self.assertIn("see https://example.com/x_y for the log",
                      page)

    def test_subcent_spread_low_end_shows(self):
        # The spread's precision stopped where its ends
        # separated, printing a sub-cent low end as $0.00
        # beside its own card's $0.004; each end now prints
        # at the precision its own figure needs, the
        # precision its card uses (contract F6, red team F2).
        payload = _payload()
        payload["ranked"][0]["total_cost_usd"] = 0.004
        payload["ranked"][1]["total_cost_usd"] = 10.0
        page = leaderboard_to_html(payload)
        self.assertIn("$0.004", page)
        self.assertNotIn("$0.00–$10.00", page)
        self.assertNotIn("$0.00 to $10.00", page)

    def test_negative_cost_is_not_a_price_on_the_card(self):
        # The tile and scatter exclude a negative cost as
        # not-a-price; the card printed it anyway, sign
        # inside the currency mark (contract F9).
        payload = _payload()
        payload["ranked"][0]["total_cost_usd"] = -5
        page = leaderboard_to_html(payload)
        self.assertNotIn("$-5.00", page)

    def test_long_single_segment_name_full_id_on_card(self):
        # The full-ID note fired only when the short name
        # differed by a dropped prefix, so a name truncated
        # by length alone showed its distinguishing tail
        # nowhere (contract F2).
        payload = _payload()
        payload["ranked"][0]["display_name"] = "a" * 45
        page = leaderboard_to_html(payload)
        self.assertIn("a" * 45, page)

    def test_chain_band_endpoints_must_overlap(self):
        # Bands are mutually overlapping runs, not chains:
        # A overlapping B and B overlapping C no longer
        # prints A tied with C when their own intervals are
        # disjoint (red team F1).
        def row(name, asr, ci):
            return {"adapter_name": name, "display_name": name,
                    "asr_conditional": asr, "asr_ci95": ci,
                    "benign_accuracy": 0.9, "n_eligible": 400,
                    "total_cost_usd": 1.0, "ece_attacked": 0.05,
                    "malformed_rate": 0.01}

        payload = {"ranked": [
            row("m-a", 0.100, [0.095, 0.105]),
            row("m-b", 0.109, [0.104, 0.114]),
            row("m-c", 0.118, [0.113, 0.123]),
            row("m-d", 0.126, [0.117, 0.136]),
        ], "unranked": []}
        page = leaderboard_to_html(payload)
        self.assertIn("The top two intervals overlap, a tie.",
                      page)
        self.assertIn("Ranks 3 to 4 overlap, a tie.", page)
        self.assertNotIn("top 4 intervals overlap", page)
        self.assertNotIn("TIED 1–4", page)

    def test_severity_yardstick_ignores_unprinted_levels(self):
        # The caption's reach ranged over every recorded
        # severity block, so an unprinted level could set
        # it, even to the whole scale, while every SEV row
        # read n/a; the yardstick reads the printed three
        # from the card's own map, case variants included
        # (contract F7).
        payload = _payload()
        for r in payload["ranked"]:
            r["detail"] = {
                "families": {}, "calibration": {},
                "severities": {"low": {
                    "flip_rate_raw": 0.5,
                    "flip_rate_ci95": [0.0, 1.0],
                    "n": 10, "n_eligible": 10}}}
        page = leaderboard_to_html(payload)
        self.assertNotIn("reach about", page)
        payload["ranked"][0]["detail"]["severities"] = {
            "Critical": {"flip_rate_raw": 0.31,
                         "flip_rate_ci95": [0.30, 0.32],
                         "n": 100, "n_eligible": 100}}
        page = leaderboard_to_html(payload)
        self.assertIn("31.0%", page)

    def test_latency_rounding_to_a_second_keeps_tenths(self):
        # 999.6 rounds to a whole 1000 at whole-ms
        # precision and printed "1000ms" under the
        # under-a-second wording, collapsing distinct
        # values; the unit is decided after rounding
        # (red team F6).
        payload = _payload()
        payload["ranked"][0]["latency_ms_p50_attacked"] = 999.6
        payload["ranked"][1]["latency_ms_p50_attacked"] = 999.9
        page = leaderboard_to_html(payload)
        self.assertIn("999.6ms", page)
        self.assertIn("999.9ms", page)
        self.assertNotIn("1000ms", page)

    def test_latency_seconds_round_half_up_not_float(self):
        # A latency whose seconds form lands exactly on a
        # third-decimal 5 must round half up like every
        # other figure on the page: float formatting
        # printed 2675ms as "2.67s" because the binary
        # value sits a hair under the exact half (pass 25).
        payload = _payload()
        payload["ranked"][0]["latency_ms_p50_attacked"] = 2675.0
        payload["ranked"][0]["latency_ms_p95_attacked"] = 1005.0
        payload["ranked"][1]["latency_ms_p50_attacked"] = 2685.0
        page = leaderboard_to_html(payload)
        self.assertIn("2.68s", page)
        self.assertIn("1.01s", page)
        self.assertIn("2.69s", page)
        self.assertNotIn("2.67s", page)
        self.assertNotIn("1.00s", page)

    def test_eligible_range_with_equal_ends_is_one_figure(self):
        # When every run rests on the same eligible count
        # the cases tile states the figure once rather
        # than printing a range whose ends agree
        # (pass 25).
        payload = _payload()
        for row in payload["ranked"] + payload["unranked"]:
            row["n_cases"] = 4701
            row["n_eligible"] = 2000
        page = leaderboard_to_html(payload)
        text = re.sub(r"\s+", " ",
                      re.sub(r"<[^>]+>", " ", page))
        self.assertIn("ELIGIBLE 2,000", text)
        self.assertNotIn("2,000–2,000", text)

    def test_scatter_cluster_stays_at_its_true_position(self):
        # Four points at one cost and rate: at most one
        # marker width of offset is available, so the
        # fourth point draws at the true position over the
        # first rather than travelling to a false one, and
        # the description discloses the overlap (red team
        # F3).
        def row(name):
            return {"adapter_name": name, "display_name": name,
                    "asr_conditional": 0.15,
                    "asr_ci95": [0.14, 0.16],
                    "benign_accuracy": 0.9, "n_eligible": 400,
                    "total_cost_usd": 30.0, "ece_attacked": 0.05,
                    "malformed_rate": 0.01}

        payload = {"ranked": [row("p-one"), row("p-two"),
                              row("p-three"), row("p-four")],
                   "unranked": []}
        page = leaderboard_to_html(payload)
        self.assertIn("drawn at their true position", page)
        i = page.find('class="chart scatter-d"')
        svg = page[page.rindex("<svg", 0, i):
                   page.index("</svg>", i)]
        centres = {(a, b) for a, b in re.findall(
            r'<circle class="pt" cx="([\d.]+)" cy="([\d.]+)"',
            svg)}
        self.assertEqual(len(centres), 3)

    def test_scatter_legend_sits_flush_and_avoids_points(self):
        # The legend box takes the bottom corner holding
        # fewer plotted points (red team F5, pass 20 residue
        # C20-2), and its bottom edge stops 8 units short of
        # the plot border: flush on the border it covered
        # the log axis's minor ticks, knocking out the first
        # decade's tick set (pass 30; reconciliation ledger
        # Theme 10).
        page = leaderboard_to_html(_payload())
        i = page.find('class="chart scatter-d"')
        svg = page[page.rindex("<svg", 0, i):
                   page.index("</svg>", i)]
        m = re.search(
            r'<rect x="([\d.]+)" y="([\d.]+)" width="150" '
            r'height="(\d+)" fill="#10141a"', svg)
        self.assertIsNotNone(m)
        _lx, _ly = float(m.group(1)), float(m.group(2))
        _lb = _ly + float(m.group(3))
        self.assertEqual(_lb, 340.0)
        # No minor tick is fully covered by the box: the
        # axis ticks stand 7 units tall off the 348 border.
        for t in re.finditer(
                r'<line x1="([\d.]+)" y1="([\d.]+)" x2="[\d.]+" '
                r'y2="([\d.]+)"', svg):
            tx, ty1, ty2 = (float(t.group(1)), float(t.group(2)),
                            float(t.group(3)))
            self.assertFalse(
                _lx <= tx <= _lx + 150 and ty1 >= _ly
                and ty2 <= _lb,
                f"minor tick at x={tx} covered by the legend")

    def test_kpi_band_grid_holds_to_1200px(self):
        # In the five-across flex row the 30px numerals
        # measure wider than their tiles from 901px to
        # about 1150px and the next tile cut them mid-glyph
        # (pass 29; reconciliation ledger Theme 7). The band
        # keeps the two-column grid until the flex row fits.
        page = leaderboard_to_html(_payload())
        self.assertIn("@media(max-width:1200px){"
                      ".kpis{display:grid", page)
        self.assertIn("@media(min-width:1201px){"
                      ".kpi-lab{min-height:46px}}", page)

    def test_phone_forms_take_over_at_900px(self):
        # Through 641-900px the desktop hero text scaled to
        # 5-10px and the desktop heat table hid its worst
        # columns with no scroll cue; the phone forms take
        # over at 900px (passes 26, 28, 29, 30; ledger
        # Theme 7). Pass 32 moved the hero swap and the duo
        # stack to 1080px, where the same scaling trough
        # runs to (hero labels at 8-10px through 901-1080);
        # the heat swap stays at 900px, its band cued by
        # the pass-31 fade and the line at the chart's head
        # (the caption's small-screens hint was retired in
        # pass 38; that line and the note's phone span carry
        # its facts). Print keeps the desktop heat table.
        page = leaderboard_to_html(_payload())
        h = page.index("@media(max-width:1080px){")
        hero_block = page[h:page.index("@media(max-width:900px){", h)]
        self.assertIn(".hero-svg{display:none}", hero_block)
        self.assertIn(".hero-mobile{display:block}",
                      hero_block)
        self.assertIn(".duo{grid-template-columns:1fr}",
                      hero_block)
        i = page.index("@media(max-width:900px){")
        block = page[i:page.index("@media(max-width:640px){", i)]
        self.assertIn(".heat-d{display:none}", block)
        self.assertIn(".heat-m{display:block}", block)
        j = page.index("@media print{")
        self.assertIn(".heat-d{display:block}",
                      page[j:j + 3000])
        self.assertIn(".heat-m{display:none}", page[j:j + 3000])

    def test_phone_heat_headers_break_at_words_only(self):
        # Anywhere breaking fragmented the phone heat
        # headers mid-word, down to a one-letter orphan
        # line (ten filings, passes 24-30; ledger Theme 1).
        page = leaderboard_to_html(_payload())
        self.assertIn("table.heat thead th{font-size:11px;"
                      "word-break:normal;overflow-wrap:normal;"
                      "max-width:none}", page)
        self.assertNotIn("table.heat thead th{font-size:11px;"
                         "word-break:normal;overflow-wrap:anywhere;"
                         "max-width:76px}", page)
        self.assertIn("table.heat{min-width:900px}", page)

    def test_strip_label_clears_the_admission_line(self):
        # A value label whose span would cross the dashed
        # admission line starts past it: the line's dashes
        # crossed the closest under-gate figure's label
        # cell and struck through its decimal point
        # (pass 30; reconciliation ledger Theme 10).
        payload = _payload()
        payload["ranked"][0]["malformed_rate"] = 0.042
        payload["ranked"][1]["malformed_rate"] = 0.119
        page = leaderboard_to_html(payload)
        i = page.find('class="chart strip-chart"')
        svg = page[page.rindex("<svg", 0, i):
                   page.index("</svg>", i)]
        line = re.search(
            r'<line x1="([\d.]+)" y1="8" x2="[\d.]+" y2="[\d.]+" '
            r'stroke="#e8a33d"', svg)
        self.assertIsNotNone(line)
        line_x = float(line.group(1))
        lab = re.search(
            r'<text x="([\d.]+)" y="[\d.]+" class="m-val[^"]*"'
            r'[^>]*>4\.2%</text>', svg)
        self.assertIsNotNone(lab)
        self.assertGreater(float(lab.group(1)), line_x)

    def test_flagged_card_name_and_asr_are_amber(self):
        # Flagged names and values are amber on every
        # surface; the cards were the one family missing
        # the flag classes (pass 24; ledger Theme 10).
        page = leaderboard_to_html(_payload())
        self.assertEqual(page.count('class="card-name flag"'),
                         1)
        self.assertEqual(page.count('class="card-asr flag"'),
                         1)
        self.assertEqual(page.count('class="card-name"'), 2)

    def test_card_full_id_note_is_labelled(self):
        # The card note's full-ID line names itself, so it
        # does not read as a second, longer model name
        # (passes 24 and 27; reconciliation ledger Theme 10).
        payload = _payload()
        payload["ranked"][0]["display_name"] = \
            "vendor/shieldstral-1.0"
        page = leaderboard_to_html(payload)
        self.assertIn("Model ID · vendor/shieldstral-1.0",
                      page)

    def test_cards_caption_states_ece_direction(self):
        # Lower-is-better for ECE and Brier is stated in
        # the cards module, not only in the footer
        # (pass 27; reconciliation ledger Theme 10).
        page = leaderboard_to_html(_payload())
        self.assertIn("where lower ECE and Brier scores "
                      "are better", page)

    def test_fitted_names_keep_canonical_suffixes(self):
        # Two vendors shipping one short name take canonical
        # suffixes; a narrow surface truncates the base, not
        # the suffix, so the strip paints the same numbers
        # its description assigns (pass 27 P1).
        payload = _payload()
        payload["ranked"] = [
            {"adapter_name": "vendor-a/shared-model-name-xyz-long",
             "adapter_version": "1", "asr_conditional": 0.10,
             "asr_ci95": [0.09, 0.11], "benign_accuracy": 0.9,
             "n_eligible": 400, "total_cost_usd": 1.0,
             "malformed_rate": 0.01},
            {"adapter_name": "vendor-b/shared-model-name-xyz-long",
             "adapter_version": "1", "asr_conditional": 0.12,
             "asr_ci95": [0.11, 0.13], "benign_accuracy": 0.9,
             "n_eligible": 400, "total_cost_usd": 1.0,
             "malformed_rate": 0.04},
        ]
        payload["unranked"] = []
        page = leaderboard_to_html(payload)
        i = page.find('class="chart strip-chart"')
        strip = page[page.rindex("<svg", 0, i):
                     page.index("</svg>", i)]
        # Worst first on the strip: the (2) row at 4.0%
        # paints above the (1) row at 1.0%.
        self.assertLess(strip.index("shared-model-name-x (2)"),
                        strip.index("shared-model-name-x (1)"))
        self.assertIn("shared-model-name-xyz-long (2) 4.0%",
                      page)

    def test_fitted_collision_never_renumbers_a_bystander(self):
        # Two names sharing a prefix longer than the hero's
        # fit budget collide only once painted; cutting the
        # colliders back for their fresh suffixes lands
        # exactly on a third name that was unique as fitted.
        # The colliders take the suffixes and the bystander
        # keeps its own name, the one its description and
        # cards print (pass 39).
        payload = _payload()
        payload["ranked"] = [
            {"adapter_name": "x/12345678901234567890123456AAAA",
             "adapter_version": "1", "asr_conditional": 0.10,
             "asr_ci95": [0.09, 0.11], "benign_accuracy": 0.9,
             "n_eligible": 400, "total_cost_usd": 1.0,
             "malformed_rate": 0.01},
            {"adapter_name": "x/12345678901234567890123456BBBB",
             "adapter_version": "1", "asr_conditional": 0.12,
             "asr_ci95": [0.11, 0.13], "benign_accuracy": 0.9,
             "n_eligible": 400, "total_cost_usd": 1.0,
             "malformed_rate": 0.04},
            {"adapter_name": "x/123456789012345678901",
             "adapter_version": "1", "asr_conditional": 0.14,
             "asr_ci95": [0.13, 0.15], "benign_accuracy": 0.9,
             "n_eligible": 400, "total_cost_usd": 1.0,
             "malformed_rate": 0.02},
        ]
        payload["unranked"] = []
        page = leaderboard_to_html(payload)
        hero = _hero_svg(page)
        self.assertIn("123456789012345678901 (1)", hero)
        self.assertIn("123456789012345678901 (2)", hero)
        self.assertIn(">123456789012345678901</text>", hero)
        self.assertNotIn("123456789012345678901 (3)", page)

    def test_float_case_count_joins_the_consensus(self):
        # A case count recorded as 2000.0 is 2,000 cases:
        # it joins the provenance consensus and triggers
        # the variation disclosure instead of letting the
        # page claim the other run's count for it (pass 27).
        payload = _payload()
        payload["ranked"][0]["n_cases"] = 4701
        payload["ranked"][1]["n_cases"] = 2000.0
        page = leaderboard_to_html(payload)
        self.assertIn("case counts vary by run", page)
        self.assertNotIn("4,701", page)

    def test_duplicate_family_records_both_print(self):
        # Two records under one family name are two recorded
        # families: the second takes a suffix and neither
        # record's figures vanish (pass 27 P1).
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": [
                {"family": "canary_leakage", "asr": 0.11,
                 "n_eligible": 400},
                {"family": "canary_leakage", "asr": 0.99,
                 "n_eligible": 400},
            ],
            "calibration": {}}
        page = leaderboard_to_html(payload)
        self.assertIn("canary leakage 11.0%", page)
        self.assertIn("canary leakage (2) 99.0%", page)

    def test_rerun_segment_bounded_by_the_run(self):
        # The re-run disclosure keys on the run_id, but a
        # run smaller than the segment cannot have had that
        # many cases re-run (passes 27 and 29).
        payload = _payload()
        payload["ranked"][0]["run_id"] = "google-v2-trial"
        payload["ranked"][0]["n_cases"] = 500
        page = leaderboard_to_html(payload)
        self.assertNotIn("First 1,610 cases", page)
        self.assertNotIn("1,610 cases of the", page)
        payload["ranked"][0]["n_cases"] = 4701
        page = leaderboard_to_html(payload)
        self.assertIn("First 1,610 cases", page)

    def test_gate_reason_prints_beside_the_derived_note(self):
        # A recorded reason that mentions a gate figure is
        # answered by the derived note, and the record
        # itself still prints, labelled as the record
        # (passes 24 and 26).
        payload = _payload()
        payload["unranked"][0].update({
            "reason": "held out: audit sample above 5 percent "
                      "of cases quarantined",
            "malformed_rate": 0.03,
        })
        page = leaderboard_to_html(payload)
        self.assertIn(
            "Malformed response rate at or under 5%", page)
        self.assertIn("Reason on record · held out: audit "
                      "sample above 5 percent of cases "
                      "quarantined", page)

    def test_ci_less_ranked_row_breaks_the_band(self):
        # A band is a run of intervals: a ranked row with a
        # rate but no interval breaks it, so the page never
        # counts "the top 3 intervals" over two (pass 25).
        payload = _payload()
        payload["ranked"] = [
            {"adapter_name": "alpha", "adapter_version": "1",
             "asr_conditional": 0.10, "asr_ci95": [0.08, 0.32],
             "benign_accuracy": 0.9, "n_eligible": 400,
             "total_cost_usd": 1.0},
            {"adapter_name": "beta", "adapter_version": "1",
             "asr_conditional": 0.20,
             "benign_accuracy": 0.9, "n_eligible": 400,
             "total_cost_usd": 1.0},
            {"adapter_name": "gamma", "adapter_version": "1",
             "asr_conditional": 0.30, "asr_ci95": [0.28, 0.35],
             "benign_accuracy": 0.9, "n_eligible": 400,
             "total_cost_usd": 1.0},
        ]
        payload["unranked"] = []
        page = leaderboard_to_html(payload)
        self.assertNotIn("the top 3 intervals overlap", page)
        self.assertNotIn("TIED 1–3", page)
        payload["ranked"][1]["asr_ci95"] = [0.15, 0.30]
        page = leaderboard_to_html(payload)
        self.assertIn("the top 3 intervals overlap, a tie",
                      page)

    def test_nfc_nfd_name_twins_take_suffixes(self):
        # Canonically equivalent spellings of one name are
        # one name: the composed and decomposed forms of a
        # model name collide and take suffixes (pass 27).
        # The spellings are built from escapes so the
        # fixture itself cannot collapse them.
        nfc = "caf\u00e9-x"
        nfd = "cafe\u0301-x"
        payload = _payload()
        payload["ranked"] = [
            {"adapter_name": nfc, "adapter_version": "1",
             "asr_conditional": 0.10, "asr_ci95": [0.09, 0.11],
             "benign_accuracy": 0.9, "n_eligible": 400,
             "total_cost_usd": 1.0},
            {"adapter_name": nfd, "adapter_version": "1",
             "asr_conditional": 0.20, "asr_ci95": [0.19, 0.21],
             "benign_accuracy": 0.9, "n_eligible": 400,
             "total_cost_usd": 1.0},
        ]
        payload["unranked"] = []
        page = leaderboard_to_html(payload)
        self.assertIn(nfc + " (1)", page)
        self.assertIn(nfd + " (2)", page)

    def test_corrupt_counts_print_as_absent(self):
        # A negative or fractional count is not a count of
        # cases: it prints as absent rather than verbatim
        # or truncated beside a share computed whole
        # (passes 25 and 29). A true integer prints exactly
        # at any magnitude (pass 27).
        payload = _payload()
        payload["ranked"][0]["n_eligible"] = 900.5
        payload["ranked"][0]["detail"] = {
            "families": {},
            "calibration": {"attacked": {"n": -100}}}
        page = leaderboard_to_html(payload)
        self.assertNotIn("-100", page)
        self.assertIn('ELIGIBLE CASES</span>'
                      '<span class="stat-val">n/a</span>', page)
        payload["ranked"][0]["n_eligible"] = 10 ** 30
        page = leaderboard_to_html(payload)
        self.assertIn(
            "1,000,000,000,000,000,000,000,000,000,000", page)

    def test_tiny_ece_prints_its_digits(self):
        # A nonzero ECE under half a thousandth is not an
        # exact zero: its digits print (pass 25).
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {},
            "calibration": {"attacked": {"ece": 0.0004}}}
        page = leaderboard_to_html(payload)
        self.assertIn(">0.0004<", page)

    def test_provenance_requires_every_carrier(self):
        # The pricing date and the manifest hash cover the
        # page's runs: one run's value does not print for
        # runs that carry none (pass 29), an integer in the
        # manifest field is not a hash (pass 27), and a date
        # that does not exist is not a run date (pass 27).
        payload = _payload()
        payload["ranked"][0]["provenance"] = {
            "pricing_date": "2026-10-01",
            "manifest_sha256": "a" * 64}
        page = leaderboard_to_html(payload)
        self.assertNotIn("pricing table dated", page)
        self.assertNotIn("manifest sha256", page)
        for row in payload["ranked"][1:] + payload["unranked"]:
            row["provenance"] = {
                "pricing_date": "2026-10-01",
                "manifest_sha256": "a" * 64}
        page = leaderboard_to_html(payload)
        self.assertIn("pricing table dated 1 October 2026",
                      page)
        self.assertIn("manifest sha256 " + "a" * 16, page)
        for row in payload["ranked"] + payload["unranked"]:
            row["provenance"] = {
                "pricing_date": "2026-10-01",
                "manifest_sha256": 1234567890123456}
        page = leaderboard_to_html(payload)
        self.assertNotIn("manifest sha256", page)
        payload = _payload()
        payload["ranked"][0]["created_utc"] = \
            "2026-02-30T00:00:00+00:00"
        page = leaderboard_to_html(payload)
        self.assertNotIn("2026-02-30", page)

    def test_non_string_suite_prints_no_repr(self):
        # A suite recorded as a list is not a suite name:
        # its Python repr never reaches the page (pass 27).
        payload = _payload()
        payload["suite"] = ["v2"]
        page = leaderboard_to_html(payload)
        self.assertNotIn("['v2']", page)
        self.assertIn("suite n/a", page)

    def test_extreme_cost_ticks_use_the_power_form(self):
        # At the far decades the plain tick forms run to
        # hundreds of characters; the tick prints the power
        # form instead (pass 27).
        payload = _payload()
        payload["ranked"][0]["total_cost_usd"] = 1e-320
        payload["ranked"][1]["total_cost_usd"] = 1e300
        page = leaderboard_to_html(payload)
        self.assertNotIn("0.00000000000000000000000000001",
                         page)
        labels = re.findall(
            r'class="s-axis"[^>]*>(\$[^<]*)</text>', page)
        self.assertTrue(any(t.startswith("$1e-")
                            for t in labels))
        self.assertLessEqual(max(len(t) for t in labels), 8)

    def test_tax_label_names_only_carried_benchmarks(self):
        # With no ranked ECE carrier anywhere, no card
        # claims an ECE benchmark (pass 27).
        payload = _payload()
        payload["ranked"] = payload["ranked"][:1]
        payload["ranked"][0].pop("ece_attacked", None)
        payload["unranked"] = []
        page = leaderboard_to_html(payload)
        self.assertIn("ROBUST TAX · VS BEST RANKED BENIGN",
                      page)
        self.assertNotIn("VS BEST RANKED RUNS", page)

    def test_headline_asr_edge_guard(self):
        # A headline rate of 0.0004 is not a perfect score:
        # it prints its digits at the scale edge (pass 29).
        payload = _payload()
        payload["ranked"][0].update({
            "adapter_name": "edge-case",
            "asr_conditional": 0.0004,
            "asr_ci95": [0.0001, 0.0015]})
        page = leaderboard_to_html(payload)
        self.assertIn("edge-case 0.04% 95% CI 0.01% to 0.2%",
                      page)

    def test_asr_less_card_interval_is_labelled(self):
        # A card with an interval but no headline rate does
        # not present the interval as the headline's own
        # (pass 27).
        payload = _payload()
        payload["ranked"][0].pop("asr_conditional")
        payload["ranked"][0]["asr_ci95"] = [0.09, 0.11]
        page = leaderboard_to_html(payload)
        self.assertIn("headline rate not recorded", page)
        self.assertNotIn("ASR · 95% CI 9.0% to 11.0%", page)

    def test_retrieval_less_card_names_its_own_spike(self):
        # A ranked run that never faced retrieval poisoning
        # has no orange bar and no silent crown: its
        # caption names its own top spike, and its note
        # names the missing family (passes 27 and 30).
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {
                "verbosity_inflation": {
                    "family": "verbosity_inflation",
                    "asr": 0.88, "n_eligible": 400}},
            "calibration": {}}
        payload["ranked"][1]["detail"] = {
            "families": {
                "retrieval_poisoning": {
                    "family": "retrieval_poisoning",
                    "asr": 0.50, "n_eligible": 400}},
            "calibration": {}}
        page = leaderboard_to_html(payload)
        card = page.split('<article class="card">')[1]
        self.assertIn("top spike is", card)
        self.assertIn("verbosity inflation 88.0%", card)
        self.assertNotIn("Orange is retrieval poisoning",
                         card)
        self.assertIn("No retrieval poisoning result "
                      "recorded", card)

    # Pass 31 fix pins.

    def test_unbounded_magnitudes_print_power_form(self):
        # A finite value past any measured quantity printed
        # plainly is a digit expansion hundreds of characters
        # long inside a nowrap tile or card (pass 31). The
        # bounded power form states the same value.
        payload = _payload()
        payload["ranked"][0]["asr_conditional"] = 1e308
        payload["ranked"][0]["robustness_tax"] = 1e308
        payload["ranked"][0]["total_cost_usd"] = 1e308
        page = leaderboard_to_html(payload)
        digits = re.findall(r"\d[\d,\.]{40,}\d", page)
        self.assertEqual([], digits)
        self.assertIn("1e+310%", page)
        self.assertIn("1e+310 pts", page)
        self.assertIn("$1e+308", page)

    def test_heat_desktop_scroll_band_carries_its_cues(self):
        # The desktop heat table measures 1000px wide, so from
        # 901px to about 1080px its last columns scroll inside
        # the wrap: the band carries the right-edge fade and
        # the caption hint, and both stay out of print
        # (pass 31).
        css = leaderboard_to_html(_payload())
        band = css.split(
            "@media(min-width:901px) and (max-width:1080px){",
            1)[1].split("@media", 1)[0]
        self.assertIn(".heat-wrap.heat-d::after", band)
        self.assertIn(".scroll-hint-d{display:inline}", band)
        payload = _payload()
        for row in payload["ranked"]:
            row["detail"] = {
                "families": {
                    "retrieval_poisoning": {
                        "family": "retrieval_poisoning",
                        "asr": 0.5, "n": 470}},
                "calibration": {}}
        self.assertIn("last families sit to the right",
                      leaderboard_to_html(payload))
        print_block = css.split("@media print{", 1)[1]
        # The phone-only span of the heat panel's own
        # reading line joins the hide list: print carries
        # the wide form, whose column order and full width
        # the span does not describe (pass 35).
        self.assertIn(".scroll-hint-d,.heat-more"
                      ",.heat-note-m{display:none}",
                      print_block[:400])

    def test_cards_two_columns_through_the_overflow_band(self):
        # The three-column grid's min-content tracks overflow
        # the page itself from 901px to 1000px (pass 31).
        css = leaderboard_to_html(_payload())
        self.assertIn("@media(max-width:1024px){"
                      ".cards{grid-template-columns:1fr 1fr}}",
                      css)

    def test_duo_panels_share_a_baseline(self):
        # A caption that wraps longer must not push its panel
        # one caption-height below its sibling (pass 31).
        css = leaderboard_to_html(_payload())
        self.assertIn(".duo section{display:flex;"
                      "flex-direction:column}", css)
        self.assertIn(".duo .panel{margin-top:auto}", css)

    def test_card_heads_stack_through_the_mid_band(self):
        # Titles wrapped mid-name beside the badge from 901px
        # to 1200px: the stacked head covers the whole band
        # (pass 31).
        css = leaderboard_to_html(_payload())
        block = css.split("@media(max-width:1200px){", 1)[1]
        block = block.split("@media", 1)[0]
        self.assertIn(".card-head{flex-direction:column",
                      block)

    def test_phone_scatter_labels_avoid_the_annotation_lines(self):
        # The phone scatter's own annotation lines (tied
        # bands, lower-bound dots) are label obstacles: on
        # the production geometry the cheapest, highest
        # ASR point's solved label sat on the lower-bound
        # line and the two texts touched (pass 32). The
        # line's text is whichever form the renderer
        # emitted — the key form on the bands line's row,
        # or the full sentence on the row below when the
        # bands line grows into the key form's stretch
        # (pass 33) — and the box is measured from the
        # emitted text, not a fixed string.
        payload = {
            "ranked": [
                {"adapter_name": "kimi-k3",
                 "adapter_version": "3",
                 "asr_conditional": 0.1095,
                 "asr_ci95": [0.1009, 0.1188],
                 "benign_accuracy": 0.9866,
                 "n_eligible": 4638, "total_cost_usd": 21.02,
                 "latency_ms_p50_attacked": 3850.0,
                 "ece_attacked": 0.0642},
                {"adapter_name": "gemini-3.8-flash",
                 "adapter_version": "3.8",
                 "asr_conditional": 0.1218,
                 "asr_ci95": [0.1126, 0.1315],
                 "benign_accuracy": 0.97,
                 "n_eligible": 4600, "total_cost_usd": 5.0,
                 "latency_ms_p50_attacked": 900.0,
                 "ece_attacked": 0.08,
                 "detail": {"families": {
                     "cryptographic_payload": {
                         "family": "cryptographic_payload",
                         "asr": 0.3, "n": 840,
                         "n_costed_calls": 825,
                         "n_latency_calls": 840}},
                     "calibration": {}}},
            ],
            "unranked": [
                {"adapter_name": "qwen3-235b-a22b-2507",
                 "adapter_version": "2507",
                 "asr_conditional": 0.2518,
                 "asr_ci95": [0.239, 0.265],
                 "benign_accuracy": 0.9,
                 "n_eligible": 4297, "total_cost_usd": 0.47,
                 "malformed_rate": 0.119,
                 "latency_ms_p50_attacked": 700.0,
                 "ece_attacked": 0.1,
                 "reason": "malformed response rate above "
                           "ranking limit"},
            ],
        }
        page = leaderboard_to_html(payload)
        svg = re.search(
            r'<svg viewBox="0 0 352 388".*?</svg>',
            page, re.S).group(0)
        dots = re.search(
            r'<text x="([\d.]+)" y="([\d.]+)" '
            r'text-anchor="end" class="s-axis">'
            r'(dots mark the lower bound costs'
            r'|lower bound dots)</text>', svg)
        self.assertIsNotNone(dots)
        dx, dy = float(dots.group(1)), float(dots.group(2))
        dbox = (dx - len(dots.group(3)) * 6.6, dy - 11,
                dx, dy + 2)
        lab = re.search(
            r'<text x="([\d.]+)" y="([\d.]+)" class="s-lab[^"]*"'
            r'[^>]*text-anchor="(\w+)"[^>]*>'
            r'qwen3-235b-a22b-2507</text>', svg)
        self.assertIsNotNone(lab)
        x, y = float(lab.group(1)), float(lab.group(2))
        w = len("qwen3-235b-a22b-2507") * 7.0
        x0 = (x if lab.group(3) == "start"
              else x - w if lab.group(3) == "end"
              else x - w / 2)
        lbox = (x0, y - 11.5, x0 + w, y)
        hit = (lbox[0] < dbox[2] + 2 and dbox[0] - 2 < lbox[2]
               and lbox[1] < dbox[3] + 2
               and dbox[1] - 2 < lbox[3])
        self.assertFalse(hit)

    def test_scatter_annotation_lines_do_not_overlap(self):
        # The panel's own annotation lines are obstacles for
        # the point labels, but nothing checked the lines
        # against each other: on the phone form the dots
        # line shared the tied-bands line's row (pass 32)
        # and at the phone text size the two together run
        # wider than the plot, so they overprinted into
        # one merged string and a cropped panel lost both
        # disclosures (pass 33, four panels). Boxes use the
        # monospace advance at each form's axis size (11px
        # desktop, 12px phone).
        payload = {
            "ranked": [
                {"adapter_name": "kimi-k3",
                 "adapter_version": "3",
                 "asr_conditional": 0.1095,
                 "asr_ci95": [0.1009, 0.1188],
                 "benign_accuracy": 0.9866,
                 "n_eligible": 4638, "total_cost_usd": 21.02,
                 "latency_ms_p50_attacked": 3850.0,
                 "ece_attacked": 0.0642},
                {"adapter_name": "gemini-3.8-flash",
                 "adapter_version": "3.8",
                 "asr_conditional": 0.1218,
                 "asr_ci95": [0.1126, 0.1315],
                 "benign_accuracy": 0.97,
                 "n_eligible": 4600, "total_cost_usd": 5.0,
                 "latency_ms_p50_attacked": 900.0,
                 "ece_attacked": 0.08,
                 "detail": {"families": {
                     "cryptographic_payload": {
                         "family": "cryptographic_payload",
                         "asr": 0.3, "n": 840,
                         "n_costed_calls": 825,
                         "n_latency_calls": 840}},
                     "calibration": {}}},
            ],
            "unranked": [
                {"adapter_name": "qwen3-235b-a22b-2507",
                 "adapter_version": "2507",
                 "asr_conditional": 0.2518,
                 "asr_ci95": [0.239, 0.265],
                 "benign_accuracy": 0.9,
                 "n_eligible": 4297, "total_cost_usd": 0.47,
                 "malformed_rate": 0.119,
                 "latency_ms_p50_attacked": 700.0,
                 "ece_attacked": 0.1,
                 "reason": "malformed response rate above "
                           "ranking limit"},
            ],
        }
        page = leaderboard_to_html(payload)
        scatters = [
            s for s in re.findall(
                r'<svg viewBox="0 0 \d+ \d+".*?</svg>',
                page, re.S)
            if "tied bands" in s]
        self.assertEqual(2, len(scatters))
        for svg in scatters:
            width = re.search(
                r'viewBox="0 0 (\d+) ', svg).group(1)
            adv = 7.2 if width == "352" else 6.6
            boxes = []
            for m in re.finditer(
                    r'<text x="([\d.]+)" y="([\d.]+)"([^>]*)>'
                    r'((?:tied bands|dots mark|lower bound dots'
                    r'|crowded points)[^<]*)</text>', svg):
                x, y = float(m.group(1)), float(m.group(2))
                w = len(m.group(4)) * adv
                x0 = (x - w if 'text-anchor="end"' in m.group(3)
                      else x)
                boxes.append(
                    (m.group(4), x0, y - 11, x0 + w, y + 2))
            self.assertGreaterEqual(len(boxes), 2)
            for i, a in enumerate(boxes):
                for b in boxes[i + 1:]:
                    hit = (a[1] < b[3] and b[1] < a[3]
                           and a[2] < b[4] and b[2] < a[4])
                    self.assertFalse(
                        hit,
                        f"width {width}: {a[0]!r} overlaps "
                        f"{b[0]!r}")

    def test_phone_hero_states_the_tie_once_per_row(self):
        # The band rides on the phone row's headline line
        # (pass 16); the sub-line repeated it, so one row
        # stated the tie twice where every other surface
        # states it once per unit (pass 34, copy panel).
        payload = {
            "ranked": [
                {"adapter_name": "kimi-k3",
                 "adapter_version": "3",
                 "asr_conditional": 0.1095,
                 "asr_ci95": [0.1009, 0.1188],
                 "benign_accuracy": 0.9866,
                 "n_eligible": 4638, "total_cost_usd": 21.02,
                 "malformed_rate": 0.0,
                 "latency_ms_p50_attacked": 3850.0,
                 "ece_attacked": 0.0642},
                {"adapter_name": "gemini-3.8-flash",
                 "adapter_version": "3.8",
                 "asr_conditional": 0.1218,
                 "asr_ci95": [0.1126, 0.1315],
                 "benign_accuracy": 0.97,
                 "n_eligible": 4600, "total_cost_usd": 5.0,
                 "malformed_rate": 0.003,
                 "latency_ms_p50_attacked": 900.0,
                 "ece_attacked": 0.08},
            ],
            "unranked": [],
        }
        page = leaderboard_to_html(payload)
        seg = page[page.index('<div class="hero-mobile">'):]
        seg = seg[:seg.index('id="malformed"')]
        rows = seg.split('<div class="mb-row">')[1:]
        self.assertEqual(2, len(rows))
        kimi = re.sub(r"<[^>]+>", "", rows[0]).lower()
        self.assertEqual(1, kimi.count("tied 1–2"))
        self.assertIn("#1 · tied 1–2", kimi)
        sub = rows[0].split('class="mb-sub"', 1)[1]
        sub = sub.split("</div>", 1)[0].lower()
        self.assertNotIn("tied", sub)

    def test_zero_cost_is_no_recorded_cost_everywhere(self):
        # Only a positive cost is a recorded cost: the tile
        # and the scatter apply that rule, and a card
        # printing "$0.00" claimed a recorded cost for a
        # run both omit, while the scatter caption claimed
        # a point per recorded-cost model (pass 34, red
        # team synthetic probe). The card now reads n/a.
        payload = {
            "ranked": [
                {"adapter_name": "free-run",
                 "adapter_version": "1",
                 "asr_conditional": 0.10,
                 "asr_ci95": [0.09, 0.11],
                 "benign_accuracy": 0.95,
                 "n_eligible": 4000, "total_cost_usd": 0.0,
                 "malformed_rate": 0.0,
                 "latency_ms_p50_attacked": 500.0,
                 "ece_attacked": 0.05},
                {"adapter_name": "paid-run",
                 "adapter_version": "1",
                 "asr_conditional": 0.20,
                 "asr_ci95": [0.19, 0.21],
                 "benign_accuracy": 0.9,
                 "n_eligible": 4000, "total_cost_usd": 10.0,
                 "malformed_rate": 0.0,
                 "latency_ms_p50_attacked": 500.0,
                 "ece_attacked": 0.05},
            ],
            "unranked": [],
        }
        page = leaderboard_to_html(payload)
        self.assertNotIn("$0.00", page)
        card = next(c for c in page.split("<article")[1:]
                    if "free-run" in c.split("</article>")[0]
                    and "card-name" in c)
        self.assertIn(
            '<span class="stat-lab">COST</span>'
            '<span class="stat-val">n/a</span>', card)

    def test_short_hyphenated_tile_name_stays_whole(self):
        # A short hyphenated endpoint name in a tile label
        # takes the nowrap class: the wrap-within-itself
        # span let the widest tile break GLM-4-PLUS after
        # its first hyphen while every sibling label
        # wrapped at word boundaries (pass 34, craft
        # panel). Long names keep the pass-18 span.
        def build(name):
            fam = {"family": "retrieval_poisoning",
                   "n_eligible": 400}
            rows = [
                {"adapter_name": "alpha",
                 "display_name": "alpha",
                 "asr_conditional": 0.20,
                 "asr_ci95": [0.19, 0.21],
                 "benign_accuracy": 0.9, "n_eligible": 400,
                 "total_cost_usd": 5.0, "ece_attacked": 0.05,
                 "malformed_rate": 0.01,
                 "detail": {"families": {
                     "retrieval_poisoning": dict(
                         fam, asr=0.80)},
                     "calibration": {}}},
                {"adapter_name": "gamma",
                 "display_name": "gamma",
                 "asr_conditional": 0.21,
                 "asr_ci95": [0.20, 0.22],
                 "benign_accuracy": 0.9, "n_eligible": 400,
                 "total_cost_usd": 5.0, "ece_attacked": 0.05,
                 "malformed_rate": 0.01,
                 "detail": {"families": {
                     "retrieval_poisoning": dict(
                         fam, asr=0.85)},
                     "calibration": {}}},
            ]
            flagged = {
                "adapter_name": name, "display_name": name,
                "asr_conditional": 0.22,
                "asr_ci95": [0.21, 0.23],
                "benign_accuracy": 0.9, "n_eligible": 400,
                "total_cost_usd": 1.0, "ece_attacked": 0.05,
                "malformed_rate": 0.10,
                "reason": "ranking-ineligible: "
                          "malformed_rate above 5%",
                "detail": {"families": {
                    "retrieval_poisoning": dict(
                        fam, asr=0.50)},
                    "calibration": {}}}
            return {"ranked": rows, "unranked": [flagged]}

        page = leaderboard_to_html(build("acme-9-plus"))
        self.assertIn(
            '<span class="nbw nbw-s">ACME-9-PLUS</span>', page)
        page = leaderboard_to_html(
            build("acme-9-plus-long-model-x"))
        self.assertIn(
            '<span class="nbw">ACME-9-PLUS-LONG-MODEL-X</span>',
            page)

    def test_phone_heat_columns_take_fixed_widths(self):
        # The phone heat table's columns are fixed so the
        # sideways scroll's cut lands in a glyph-free zone
        # at the common phone widths instead of through a
        # centred numeral (pass 34, mobile panel: whole
        # leading digits printed as smaller values).
        css = leaderboard_to_html(_payload())
        block = css.split("@media(max-width:640px){", 1)[1]
        block = block.split("@media", 1)[0]
        self.assertIn(
            ".heat-wrap.heat-m table{table-layout:fixed;"
            "width:1315px}", block)
        self.assertIn(
            ".heat-wrap.heat-m thead th{width:110px}", block)
        self.assertIn(
            ".heat-wrap.heat-m th.row-name{width:105px}",
            block)

    def test_strip_header_clears_the_first_value_label(self):
        # The "worst first" header's box cleared the first
        # row's value label by under 2.5px at every width:
        # the rows start 3 units lower (pass 32).
        payload = _payload()
        payload["ranked"][0]["malformed_rate"] = 0.02
        payload["ranked"][1]["malformed_rate"] = 0.11
        page = leaderboard_to_html(payload)
        strip = page.split('class="chart strip-chart"', 1)[1]
        strip = strip[:strip.index("</svg>")]
        head = re.search(
            r'<text x="500" y="([\d.]+)" class="m-axis" '
            r'text-anchor="end">worst first</text>', strip)
        self.assertIsNotNone(head)
        names = re.findall(
            r'<text x="150" y="([\d.]+)" class="m-name', strip)
        self.assertTrue(names)
        first_value_y = float(names[0])
        # Name and value share the row baseline; the value
        # box top sits 12.5 units above it and the header
        # box ends at its own baseline.
        clearance = (first_value_y - 12.5) - float(
            head.group(1))
        self.assertGreaterEqual(clearance, 5.0)

    def test_kpi_grid_spans_balance_the_wide_tile(self):
        # Six grid columns at 1200px and below: plain tiles
        # span two, the wide cost tile and the retrieval tile
        # span three, so the wide tile no longer sits
        # left-packed in a full-width row (pass 31).
        css = leaderboard_to_html(_payload())
        self.assertIn("grid-template-columns:repeat(6,1fr)",
                      css)
        self.assertIn(".kpi{grid-column:span 2}", css)
        self.assertIn(".kpi.wide{grid-column:span 3}", css)
        self.assertIn(".kpi.span3{grid-column:span 3}", css)
        payload = _payload()
        for row in payload["ranked"]:
            row["detail"] = {
                "families": {
                    "retrieval_poisoning": {
                        "family": "retrieval_poisoning",
                        "asr": 0.5, "n_eligible": 400}},
                "calibration": {}}
        page = leaderboard_to_html(payload)
        self.assertIn('class="kpi span3"', page)
        # Phones keep the two-column grid: three-across
        # tiles at 390px clip their own numerals. The
        # retrieval tile pairs beside the lead tile there
        # (span auto, as before the spans existed): at
        # span 2 it orphaned the lead tile and left an
        # empty half-row beside it (pass 32, reversing the
        # span-2 phone rule pass 31 added).
        phone = css.split("@media(max-width:640px){", 1)[1]
        phone = phone.split("@media", 1)[0]
        self.assertIn(".kpis{grid-template-columns:"
                      "repeat(2,1fr)", phone)
        self.assertIn(".kpi{grid-column:auto}", phone)
        self.assertIn(".kpi.span3{grid-column:auto}", phone)
        self.assertIn("grid-auto-rows:auto", phone)
        # Equal tile-row heights through the grid band:
        # the retrieval label wraps one line deeper than
        # its neighbours in the 1024-1150 window and at
        # 641px (pass 32).
        self.assertIn("grid-auto-rows:1fr", css)

    def test_heat_panel_carries_its_own_reading_line(self):
        # The heatmap panel states its row order, its ties
        # and the flagged rows' lack of rank inside its own
        # border, like the ranking, scatter and malformed
        # panels state theirs: cropped or shared alone, the
        # table otherwise reads as a strict one-to-twelve
        # ranking with the lead row crowned and the
        # eighth-ranked model sitting tenth, its rank
        # stated nowhere in the panel (pass 35, red team).
        payload = _payload()
        payload["ranked"][1]["asr_ci95"] = [0.18, 0.30]
        for row in payload["ranked"]:
            row["detail"] = {
                "families": {
                    "retrieval_poisoning": {
                        "family": "retrieval_poisoning",
                        "asr": 0.5, "n_eligible": 400}},
                "calibration": {}}
        page = leaderboard_to_html(payload)
        note = page.index('class="heat-note"')
        panel = page.rindex('<div class="panel">', 0, note)
        wrap = page.index('class="heat-wrap', note)
        self.assertLess(panel, note)
        self.assertLess(note, wrap)
        line = page[note:wrap]
        self.assertIn("rows in overall ASR order", line)
        self.assertIn("intervals overlap, a tie", line)
        self.assertIn("flagged rows carry no rank", line)
        self.assertIn('class="heat-note-m"', line)
        self.assertIn("families run by average attack "
                      "success", line)

    def test_tax_stat_row_reserves_its_second_line(self):
        # The benchmark setter's robust tax label wraps to
        # two lines where every other card's takes one, so
        # its card's lower stat rows sat 10px below its row
        # peers'. The tax row carries a class on every card
        # and the stylesheet reserves the second label line
        # for it, keeping the rows in register (pass 35).
        page = leaderboard_to_html(_payload())
        cards = page.split('<article class="card')[1:]
        self.assertTrue(cards)
        for card in cards:
            self.assertEqual(
                card.count('<div class="stat tax">'), 1)
        self.assertIn(".stat.tax .stat-lab{min-height:28px}",
                      page)

    def test_duo_captions_sit_at_their_block_foot(self):
        # The duo caption blocks share one height but carry
        # different amounts of text: the text anchors to
        # the block's foot, so the shorter caption hugs its
        # panel instead of floating over a dead band the
        # taller caption does not have (pass 35).
        page = leaderboard_to_html(_payload())
        self.assertIn(
            ".duo .cap{display:flex;flex-direction:column;"
            "justify-content:flex-end}", page)

    def test_degenerate_payload_strings_are_capped(self):
        # Payload strings outside the chart-name surfaces
        # (family prose, the card Model ID note, the suite
        # and dataset assertions, the run-notes name) are
        # length-capped like the names are: a degenerate
        # value is escaped everywhere but was printed whole
        # in a dozen places, bloating the page (pass 35).
        payload = _payload()
        fam = "x" * 5000
        payload["suite"] = "z" * 5000
        payload["ranked"][0]["adapter_name"] = "y" * 5000
        for row in payload["ranked"]:
            row["detail"] = {
                "families": {fam: {"family": fam, "asr": 0.5,
                                   "n_eligible": 400}},
                "calibration": {}}
        page = leaderboard_to_html(payload)
        self.assertNotIn("x" * 200, page)
        self.assertNotIn("y" * 200, page)
        self.assertNotIn("z" * 200, page)
        self.assertIn("x" * 60, page)

    def test_reason_prints_capped_on_flagged_cards(self):
        # The flagged card's reason was the one payload
        # string still printing at unbounded length: the
        # humanized text is escaped at every print site
        # but was never truncated, so a degenerate
        # registry reason ballooned the card note (pass
        # 36). The comparison against the derived gate
        # sentence keeps the full text; the prints cap.
        payload = _payload()
        payload["unranked"][0]["reason"] = (
            "malformed rate above 99% because " + "G" * 5000)
        payload["unranked"][0]["malformed_rate"] = 0.09
        page = leaderboard_to_html(payload)
        self.assertIn("Reason on record", page)
        self.assertNotIn("G" * 300, page)
        payload = _payload()
        payload["unranked"][0]["reason"] = "R" * 5000
        page = leaderboard_to_html(payload)
        self.assertNotIn("R" * 300, page)
        # An ordinary reason still prints whole.
        page = leaderboard_to_html(_payload())
        self.assertIn("benign accuracy below ranking "
                      "floor", page.lower())

    def test_invisible_suite_and_dataset_read_na(self):
        # A suite or dataset version made only of
        # invisible characters is not a carrier for the
        # page-wide assertion: keyed on raw truthiness it
        # passed the consensus gate and printed as a
        # blank in the header tag and the provenance
        # (pass 36; the pass-23 cleaned-name rule).
        payload = _payload()
        payload["suite"] = "\u200b\u202e"
        payload["dataset_version"] = "\u200b\u202e"
        page = leaderboard_to_html(payload)
        self.assertIn("suite n/a", page)
        self.assertIn("dataset n/a", page)

    def test_run_notes_name_falls_back_to_run_id(self):
        # A re-run run whose display name cleans to
        # nothing is still named in the run notes, by
        # its run_id: the fallback keyed on raw
        # truthiness, so the sentence named a blank run
        # while the run's identity sat unused (pass 36).
        payload = _payload()
        payload["ranked"][0]["run_id"] = "google-v2-trial"
        payload["ranked"][0]["display_name"] = "\u200b\u202e\u200b"
        page = leaderboard_to_html(payload)
        self.assertIn("The first 1,610 cases of the "
                      "google-v2-trial run", page)
        self.assertNotIn("of the  run", page)


class TestPass39Reopened(unittest.TestCase):
    """Pass 39, reopened adjudication: the true panel docket.

    The full reviewer handoffs, read end to end after the
    pass first closed, carried six contract items and three
    red-team deceptions the coordinator's digests had not.
    Each fix below is pinned the way the earlier ones are:
    revert the guard and the test fails.
    """

    def _with_families(self, fams0, fams1=None):
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": fams0, "calibration": {}}
        if fams1 is not None:
            payload["ranked"][1]["detail"] = {
                "families": fams1, "calibration": {}}
        return payload

    def test_corrupt_count_magnitude_falls_back_not_crashes(self):
        # F1: the exact-derivation agreement check quantized
        # a 10**396 count ratio past its context and raised
        # InvalidOperation out of the render.
        payload = self._with_families({
            "retrieval_poisoning": {
                "family": "retrieval_poisoning", "asr": 0.5,
                "n_flipped": 10 ** 396, "n_eligible": 1,
            },
        })
        page = leaderboard_to_html(payload)
        self.assertIn("shieldstral-1.0", page)
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {}, "calibration": {},
            "severities": {
                "critical": {
                    "flip_rate_raw": 0.1,
                    "n_flipped": 10 ** 396, "n_eligible": 1,
                },
            },
        }
        page = leaderboard_to_html(payload)
        self.assertIn("shieldstral-1.0", page)

    def test_heat_cell_corrupt_magnitude_prints_power_form(self):
        # F4: the visible cell was the one rate surface with
        # no magnitude bound.
        payload = self._with_families({
            "retrieval_poisoning": {
                "family": "retrieval_poisoning", "asr": 1e308,
            },
        })
        page = leaderboard_to_html(payload)
        self.assertIn('aria-hidden="true">1e+310<', page)
        self.assertIsNone(re.search(r"\d{60,}", page))

    def test_fmt3_bounds_both_ends(self):
        # F5 and F6: a huge score printed as a digit
        # expansion and a tiny one in raw E-notation.
        from peira.report_html import _fmt3
        self.assertEqual(_fmt3(1e308), "1e+308")
        self.assertEqual(_fmt3(1e-7), "0.0000001")
        self.assertEqual(_fmt3(1e-35), "1e-35")
        self.assertEqual(_fmt3(0.0642), "0.064")
        self.assertEqual(_fmt3(0), "0.000")

    def test_provenance_padding_cannot_blank_the_assertion(self):
        # F2: suite and dataset truncate after cleaning, so
        # invisible padding cannot strand the visible text.
        payload = _payload()
        for r in payload["ranked"] + payload["unranked"]:
            r["suite"] = "\u200b" * 100 + "v9"
        payload["suite"] = "\u200b" * 100 + "v9"
        page = leaderboard_to_html(payload)
        self.assertIn("suite v9", page)

    def _rerun_payload(self):
        payload = _payload()
        payload["ranked"][0]["run_id"] = "google-v2-trial"
        payload["ranked"][0]["n_cases"] = 4701
        return payload

    def test_run_notes_name_guards(self):
        # F3: a non-string display name falls back to the
        # run_id instead of printing its repr, and a padded
        # name prints its visible text.
        payload = self._rerun_payload()
        payload["ranked"][0]["display_name"] = {"evil": 1}
        page = leaderboard_to_html(payload)
        self.assertIn("of the google-v2-trial run", page)
        self.assertNotIn("evil", page)
        payload = self._rerun_payload()
        payload["ranked"][0]["display_name"] = (
            "\u200b" * 100 + "realrun")
        page = leaderboard_to_html(payload)
        self.assertIn("of the realrun run", page)

    def test_run_notes_colliding_names_disambiguate(self):
        # Re-audit F1: the disclosure names each affected
        # run distinctly, like every other surface.
        payload = self._rerun_payload()
        payload["ranked"][0]["display_name"] = "Acme "
        payload["unranked"][0]["run_id"] = "moonshot-v2-trial"
        payload["unranked"][0]["display_name"] = "Acme"
        page = leaderboard_to_html(payload)
        self.assertIn("Acme (1)", page)
        self.assertIn("Acme (2)", page)
        self.assertNotIn("of the Acme run", page)

    def test_provenance_whitespace_padding_cannot_blank(self):
        # Re-audit A1: the asserted suite is stripped as
        # well as cleaned, so padding of ordinary spaces
        # or no-break spaces cannot fill the cap either.
        for pad in (" " * 100, " " * 100):
            payload = _payload()
            for r in payload["ranked"] + payload["unranked"]:
                r["suite"] = pad + "v9"
            payload["suite"] = pad + "v9"
            page = leaderboard_to_html(payload)
            self.assertIn("suite v9", page)

    def test_run_notes_same_run_id_cap_collision_names_both(self):
        # Re-audit A2: the dedupe keys on the recorded
        # name, so two affected rows sharing a run_id
        # whose names differ only past the cap both print,
        # disambiguated, instead of one going unnamed.
        payload = self._rerun_payload()
        payload["ranked"][0]["display_name"] = "A" * 80 + "X"
        payload["ranked"][1]["run_id"] = "google-v2-trial"
        payload["ranked"][1]["display_name"] = "A" * 80 + "Y"
        page = leaderboard_to_html(payload)
        self.assertIn("A" * 80 + " (1)", page)
        self.assertIn("A" * 80 + " (2)", page)
        payload = self._rerun_payload()
        payload["ranked"][0]["display_name"] = "​Acme"
        payload["ranked"][1]["run_id"] = "google-v2-trial"
        payload["ranked"][1]["display_name"] = "Acme"
        page = leaderboard_to_html(payload)
        self.assertIn("Acme (1)", page)
        self.assertIn("Acme (2)", page)

    def test_negative_rate_keeps_its_sliver(self):
        # Re-audit A4: a negative rate prints its signed
        # figure, so it draws the sliver the caption
        # promises every nonzero rate, not a true zero's
        # absence.
        payload = self._with_families({
            "canary_leakage": {
                "family": "canary_leakage", "asr": -0.1,
                "n_eligible": 470,
            },
        })
        page = leaderboard_to_html(payload)
        self.assertIn('style="height:1px" '
                      'title="canary leakage -10.0% · n 470"',
                      page)

    def test_run_notes_names_print_without_edge_whitespace(self):
        # Re-audit residue: a recorded trailing space in a
        # note name printed as a doubled space before
        # "run", and a literal suffixed name among colliders
        # keeps its own form while the colliders number
        # around it.
        payload = self._rerun_payload()
        payload["ranked"][0]["display_name"] = "Acme "
        page = leaderboard_to_html(payload)
        self.assertIn("of the Acme run", page)
        self.assertNotIn("Acme  run", page)
        payload = self._rerun_payload()
        payload["ranked"][0]["display_name"] = "Acme "
        payload["unranked"][0]["run_id"] = "moonshot-v2-trial"
        payload["unranked"][0]["display_name"] = "Acme"
        payload["ranked"][1]["run_id"] = "google-v2-trial"
        payload["ranked"][1]["display_name"] = "Acme (2) "
        page = leaderboard_to_html(payload)
        for frag in ("the Acme (1) run", "the Acme (2) run",
                     "the Acme (3) run"):
            self.assertIn(frag, page)
        self.assertNotIn("Acme (2)  run", page)

    def test_whitespace_only_segment_keeps_a_name(self):
        # Re-audit F2: the short name is the last segment
        # carrying visible text.
        from peira.report_html import _short_raw
        self.assertEqual(
            _short_raw({"display_name": "vendorone/   "}),
            "vendorone")
        self.assertEqual(
            _short_raw({"display_name": "abc/"}), "abc")
        self.assertEqual(
            _short_raw({"display_name": "upstage/solar-pro4"}),
            "solar-pro4")

    def test_spark_caption_names_the_true_top_spike(self):
        # Red team 1: where the top non-retrieval family's
        # printed figure beats retrieval's, the caption
        # names it as the top spike, not the runner-up.
        payload = self._with_families(
            {
                "retrieval_poisoning": {
                    "family": "retrieval_poisoning",
                    "asr": 0.595, "n": 470,
                },
                "verbosity_inflation": {
                    "family": "verbosity_inflation",
                    "asr": 0.738, "n": 470,
                },
            },
            {
                "retrieval_poisoning": {
                    "family": "retrieval_poisoning",
                    "asr": 0.60, "n": 470,
                },
                "verbosity_inflation": {
                    "family": "verbosity_inflation",
                    "asr": 0.30, "n": 470,
                },
            })
        page = leaderboard_to_html(payload)
        cards = page.split("<article")[1:]
        card = "<article" + cards[0]
        self.assertIn("top spike is", card)
        self.assertNotIn("top other spike", card)
        self.assertIn("73.8%", card)
        card = "<article" + cards[1]
        self.assertIn("top other spike is", card)

    def test_sliver_caption_states_the_floor_not_a_bound(self):
        # Red team 3: a 1px spark bar encodes up to about
        # 3 percent on the 46px scale, so the caption states
        # the floor's guarantee, not a 1 percent bound.
        payload = self._with_families({
            "retrieval_poisoning": {
                "family": "retrieval_poisoning", "asr": 0.5,
                "n": 470,
            },
        })
        page = leaderboard_to_html(payload)
        self.assertIn(
            "a nonzero rate always draws at least a 1px "
            "sliver, so a missing bar is a true zero", page)
        self.assertNotIn("under about 1%", page)


class WireNoteTest(unittest.TestCase):
    """Two rows for one model measured over two wires.

    The data layer keys leaderboard entries by model ID plus wire,
    so one model can appear twice with the same display name. The
    cards must not read as one model printed twice: each colliding
    card names its wire. A model that appears once gets no wire
    note; its header already identifies it.
    """

    def _two_wire_payload(self):
        row = {
            "display_name": "gpt-6-luna",
            "adapter_version": "gpt-6-luna",
            "asr_ci95": [0.15, 0.26],
            "benign_accuracy": 0.97,
            "n_eligible": 400,
            "total_cost_usd": 1.23,
            "latency_ms_p50_attacked": 210.5,
            "ece_attacked": 0.04,
        }
        chat = dict(row, adapter_name="openai-structured",
                    wire="openai-structured", asr_conditional=0.30)
        dec = dict(row, adapter_name="openai-decisions",
                   wire="openai-decisions", asr_conditional=0.20)
        return {"ranked": [dec, chat], "unranked": []}

    def test_same_model_cards_name_their_wire(self):
        page = leaderboard_to_html(self._two_wire_payload())
        self.assertIn("Wire · openai-decisions", page)
        self.assertIn("Wire · openai-structured", page)
        # Both measurements are on the page with their own rates.
        self.assertIn("20.0%", page)
        self.assertIn("30.0%", page)

    def test_single_entry_per_model_has_no_wire_note(self):
        page = leaderboard_to_html(_payload())
        self.assertNotIn("Wire ·", page)


if __name__ == "__main__":
    unittest.main()
