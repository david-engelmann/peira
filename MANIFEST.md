# Manifest — peira v2 freeze archive, 2026-10-23

Every sealed trial artifact in seals/, with its file md5 and the headline
figures in payloads/payload-freeze.json. Each seal is a RunArtifact JSON
carrying its own hash lock; peira's RunArtifact.verify() re-checks it.

| Seal file | md5 | Model | ASR | Benign | Malformed |
|---|---|---|---|---|---|
| anthropic-fable-v2-trial.json | 26c6d8176d1bcb211dfef8cdcb07bf39 | claude-fable-5-1 | 0.285 | 0.9774 | 0.0091 |
| anthropic-haiku-v2-trial.json | 34188597f1d5be2840b68dacd6cd8080 | claude-haiku-5-5 | 0.1538 | 0.9784 | 0.0079 |
| anthropic-opus-v2-trial.json | 4bdccad26a34020889cc03416ae806b2 | claude-opus-5-5 | 0.2428 | 0.9827 | 0.0051 |
| anthropic-v2-trial.json | 7de23e7ec417b68260c7a4a7360a285a | claude-sonnet-5-5 | 0.2157 | 0.9825 | 0.0126 |
| celeris-v2-trial.json | 2089c0ae54fa5226c70aa4947ed51ad4 | celeris-1-decision | 0.1696 | 0.9785 | 0.0 |
| clef-flash-v2-trial.json | df972d24eb4269188699e69f5ef9ab68 | @cf/cloudflare/clef-flash | 0.1908 | 0.9691 | 0.0009 |
| clef-omni-v2-trial.json | adb1b64b924c5e02972438a868894583 | @cf/cloudflare/clef-omni | 0.2024 | 0.9832 | 0.0045 |
| clef-v2-trial.json | 761992e5429f66bf3e4f23386f7c996c | @cf/cloudflare/clef | 0.1397 | 0.9815 | 0.0011 |
| decider-v2-trial.json | a4161652b4faad1b404dd66331d76d2e | Mapika/decider-0.8b@a0a01d6f8135298f400a8c856b355793012ae971 | 0.2149 | 0.9056 | 0.0 |
| deepseek-v2-trial.json | f4355de322d71eba8da62edefe9f3a95 | deepseek-flash | 0.1242 | 0.9851 | 0.0 |
| google-v2-trial.json | b92a64e207f691c1aa0cac3ff69c642c | gemini-3.8-flash | 0.1218 | 0.977 | 0.0032 |
| granite-guardian-v2-trial.json | a5d30ab570c2de217e6d17dacf44a785 | 1.0 | 0.0912 | 1.0 | 0.0 |
| granite-hap-v2-trial.json | 230e02dc763a59be25d575d62cd3fe28 | 125m | 0.0 | 1.0 | 0.0 |
| jev-114-v2-trial.json | e26dff8f159e05a87e14beb785d1e504 | jev-1.14.0 | 0.1106 | 0.9872 | 0.0006 |
| jev-v2-trial.json | fcf2db28858c88210e035bec9f76ed71 | jev-1.13.0 | 0.1263 | 0.9858 | 0.0126 |
| kev-4b-v2-trial.json | 218c2e25e03679d4be9f053bbef73574 | jaredpalmer/kev-4b | 0.239 | 0.9487 | 0.0 |
| laya-multilingual-v2-trial.json | a8f5067e6769227e14bef63b3b60bca7 | convaiinnovations/laya-multilingual | 0.2403 | 0.793 | 0.0 |
| mercury-decide-v2-trial.json | 949a09c505b8bf12e6cb649fdd71d155 | mercury-decide | 0.1649 | 0.9806 | 0.0151 |
| minimax-v2-trial.json | c1a5a3d07acd2b1f489229b8216c4226 | MiniMax-M3 | 0.2176 | 0.9784 | 0.0423 |
| moonshot-v2-trial.json | afb00137d54e644c2d9f2fca44570518 | kimi-k3 | 0.1095 | 0.9866 | 0.0 |
| openai-astra-v2-trial.json | d0adf2dc4742a730d4eea4e812c87757 | gpt-6-astra | 0.1128 | 0.9715 | 0.0002 |
| openai-decisions-v2-trial.json | 4b635a8ef089f2f37b580d377a701d30 | gpt-6-luna | 0.107 | 0.963 | 0.0 |
| openai-luna6-v2-trial.json | c5a2450d3059701860ca9044c239d5c6 | gpt-6-luna | 0.1233 | 0.9664 | 0.0243 |
| openai-sol-v2-trial.json | 889c5fea45fd1605661288f257b1513d | gpt-6.1-sol | 0.1067 | 0.9747 | 0.0009 |
| openai-terra56-v2-trial.json | 34095e86e28171b356178bb5f63e62a3 | gpt-5.6-terra | 0.1065 | 0.9789 | 0.0072 |
| openai-v2-trial.json | 03116fe26a4124bf74e4832d08261238 | gpt-5.6-luna | 0.1652 | 0.9783 | 0.0221 |
| or-ling-v2-trial.json | 4d79186626288dae3c9ae0de8ab57cff | inclusionai/ling-3.0-flash | 0.2284 | 0.9827 | 0.0728 |
| or-lingvl-v2-trial.json | a1c8deb2729de4a1a0e388cfa95034fb | inclusionai/ling-3.0-flash-vl | 0.2089 | 0.983 | 0.107 |
| or-qwen-v2-trial.json | 9f027cec10bd6acf16d4100642634427 | qwen/qwen3-235b-a22b-2507 | 0.2518 | 0.9775 | 0.1191 |
| or-solar-v2-trial.json | 8f3e5156941b9ff71427ff0a4f706365 | upstage/solar-pro4 | 0.1742 | 0.9768 | 0.006 |
| pplx-decider-v2-trial.json | b49abee0c1a7c64c962e1b73b343ed85 | pplx-decider-v1.1-27b | 0.1483 | 0.9847 | 0.0009 |
| prompt-guard-2-v2-trial.json | a3e2896032af20c7fcdb533a7b4d4ba7 | 2.0 | 0.1796 | 1.0 | 0.0 |
| protectai-v2-trial.json | dd54dd0e63394157407941379c5211d8 | 2.0 | 0.0402 | 1.0 | 0.0 |
| qwen3guard-v2-trial.json | 9417eac47cce5e3e4e78c9c85caf4d1e | 1.0 | 0.008 | 1.0 | 0.0 |
| semif-v2-trial.json | 946915d6210d2d620006e8c64e4d7963 | Qwen/Qwen3.5-4B@851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a | 0.2508 | 0.9713 | 0.0 |
| shieldstral-v2-trial.json | a802ae0fece58aec7b015ea3938f3cbf | 1.0 | 0.0055 | 1.0 | 0.0241 |
| strands-v2-trial.json | bc5532504049177b2bccfe0fc8227d41 | StrandsAgents/strands-decider-2B-hobson-v21 | 0.2417 | 0.963 | 0.0 |
| xai-v2-trial.json | 389fe52baa033c8ffdfb10aeea7ffee5 | grok-4 | 0.1608 | 0.983 | 0.0 |
| zai-v2-trial.json | 8fbd3753920816df23f26fc777a6fa42 | glm-4-plus | 0.2101 | 0.9891 | 0.0619 |
