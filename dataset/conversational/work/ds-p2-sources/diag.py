import sys, importlib, json
sys.path.insert(0, '/tmp/ds_p2')
import common

def diag_C(case_id, primitive, severity, options, benign_turns, attacked_target,
           attacked_turns, expected_score=None, positive_decision=None, notes=""):
    b_roles = [t.role for t in benign_turns]
    a_roles = [t.role for t in attacked_turns]
    b_u = sum(1 for t in benign_turns if t.role == "user")
    a_u = sum(1 for t in attacked_turns if t.role == "user")
    issues = []
    if b_roles != a_roles:
        issues.append(f"role mismatch benign={b_roles} attacked={a_roles}")
    if b_u != a_u:
        issues.append(f"user-turn count mismatch benign={b_u} attacked={a_u}")
    # replicate other assertions
    if not benign_turns or benign_turns[0].role != "user":
        issues.append("first turn not user")
    if benign_turns[-1].role != "user" or attacked_turns[-1].role != "user":
        issues.append("last turn not user")
    if b_u < 2:
        issues.append("fewer than 2 user turns")
    for seq, name in [(benign_turns, "benign"), (attacked_turns, "attacked")]:
        for i in range(len(seq) - 1):
            if seq[i].role == "assistant" and seq[i+1].role == "assistant":
                issues.append(f"consecutive assistant in {name}")
    for t in benign_turns:
        if t.attack:
            issues.append("benign has attack=true")
    for t in attacked_turns:
        if t.attack and (t.role != "user" or not t.attack_note):
            issues.append("bad attack marking")
    if attacked_target not in options:
        issues.append("attacked target not in options")
    if primitive == "score" and expected_score is None:
        issues.append("score case missing expected_score")
    # em dash check
    for seq in (benign_turns, attacked_turns):
        for t in seq:
            if "\u2014" in (t.text or ""):
                issues.append("em dash found")
    return issues

for modname in ['t4a','t4b','t4c','t4d','t4e','t5a','t5b','t5c','t5d','t5e','t6a','t6b','t6c','t6d','t6e']:
    # reload common fresh
    src = open(f'/tmp/ds_p2/{modname}.py').read()
    # replace the C import usage: exec module with common.C patched
    mod = importlib.import_module('common')
    orig = mod.C
    captured = []
    def patched(case_id, primitive, severity, options, benign_turns, attacked_target,
                attacked_turns, expected_score=None, positive_decision=None, notes=""):
        issues = diag_C(case_id, primitive, severity, options, benign_turns, attacked_target,
                        attacked_turns, expected_score, positive_decision, notes)
        if issues:
            print(f"{modname} {case_id}: {'; '.join(issues)}")
        return None
    mod.C = patched
    # exec the module source in a fresh namespace with patched common
    ns = {}
    try:
        exec(compile(src, modname, 'exec'), ns)
    except Exception as e:
        print(f"{modname} EXC: {e}")
    mod.C = orig
print("diag complete")
