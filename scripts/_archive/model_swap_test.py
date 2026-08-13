#!/usr/bin/env python3
"""
Model-swap quality/cost test for outreach generation via the Claude API.

Runs the SAME prospect bundle(s) through several models, using the generate-outreach
SKILL.md as a cached system prompt, and saves each model's authored JSON result so the
quality can be compared side by side. Prints per-call token usage + cost.

Defaults to 3 prospects we already hand-authored in-session (message_results.json), so
those serve as the gold-reference to grade each model against.

Usage:
  pip install anthropic
  # ANTHROPIC_API_KEY in .env or environment
  python scripts/model_swap_test.py                         # default 3 domains, 3 models
  python scripts/model_swap_test.py --models opus,sonnet    # subset
  python scripts/model_swap_test.py --domains nca.org/      # one domain
"""
import argparse, json, os, re, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUNDLES = ROOT / "data" / "message_bundles_all.json"
SKILL = ROOT / ".claude" / "skills" / "generate-outreach" / "SKILL.md"
OUTDIR = ROOT / "data" / "model_swap"

# id + $/token (input, output). Prompt-cache: write 1.25x in, read 0.10x in.
MODELS = {
    "opus":   ("claude-opus-4-8",  5e-6,  25e-6),
    "sonnet": ("claude-sonnet-5",  3e-6,  15e-6),   # std rates; intro is lower
    "haiku":  ("claude-haiku-4-5", 1e-6,   5e-6),
    "fable":  ("claude-fable-5",  10e-6,  50e-6),
}
DEFAULT_MODELS = ["opus", "sonnet", "haiku"]
DEFAULT_DOMAINS = ["www.simplyblock.io", "nca.org/", "www.cirkledin.com/"]


def load_env():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    envf = ROOT / ".env"
    if envf.exists():
        for line in envf.read_text().splitlines():
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY") and "=" in line:
                os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")


def build_system():
    data = json.loads(BUNDLES.read_text())
    dd = data["data_dictionary"]
    text = SKILL.read_text() + "\n\n## DATA DICTIONARY (field meanings for the bundle)\n" + json.dumps(dd, indent=2)
    return text, {p["domain"]: p for p in data["prospects"]}


USER_INSTR = (
    "You are given ONE prospect bundle below (JSON). Ignore any procedure in the system "
    "prompt about dump/assemble scripts or writing files. Author the 3-message outreach "
    "for THIS ONE prospect following every rule in the system prompt, and output ONLY a "
    "single JSON object matching the OUTPUT SCHEMA (all fields, including angle_rationale "
    "and case_study_rationale). No prose, no markdown, just the JSON object.\n\nBUNDLE:\n"
)


def extract_json(text):
    # strict=False tolerates literal newlines/tabs inside string values (models emit them);
    # never raise -> a bad parse just yields None so one prospect can't crash the run.
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(json)?", "", text).rsplit("```", 1)[0].strip()
    for cand in (text, (re.search(r"\{.*\}", text, re.DOTALL) or type("", (), {"group": lambda *_: None})).group(0)):
        if not cand:
            continue
        try:
            return json.loads(cand, strict=False)
        except Exception:
            continue
    return None


def cost(usage, in_rate, out_rate):
    ci = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cr = getattr(usage, "cache_read_input_tokens", 0) or 0
    it = usage.input_tokens or 0
    ot = usage.output_tokens or 0
    return it * in_rate + ci * 1.25 * in_rate + cr * 0.10 * in_rate + ot * out_rate, (it, ci, cr, ot)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--domains", default=",".join(DEFAULT_DOMAINS))
    ap.add_argument("--max-tokens", type=int, default=4000)
    ap.add_argument("--thinking", default="off", choices=["off", "on"],
                    help="on = adaptive thinking + effort medium (opus/sonnet)")
    args = ap.parse_args()

    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("No ANTHROPIC_API_KEY found (checked env and .env).")
    try:
        import anthropic
    except ImportError:
        sys.exit("anthropic SDK not installed. Run: pip install anthropic")

    client = anthropic.Anthropic()
    system_text, by_domain = build_system()
    system = [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}]
    OUTDIR.mkdir(parents=True, exist_ok=True)

    models = [m.strip() for m in args.models.split(",")]
    domains = [d.strip() for d in args.domains.split(",")]
    total = 0.0

    for dom in domains:
        if dom not in by_domain:
            print(f"!! {dom} not in bundles, skipping"); continue
        user = USER_INSTR + json.dumps(by_domain[dom]["bundle"], indent=2, default=str)
        print(f"\n{'='*70}\nPROSPECT: {dom}\n{'='*70}")
        for mkey in models:
            model_id, in_rate, out_rate = MODELS[mkey]
            t0 = time.time()
            think_on = args.thinking == "on" and mkey in ("opus", "sonnet")
            mx = 6000 if think_on else args.max_tokens
            base = dict(model=model_id, max_tokens=mx,
                        system=system, messages=[{"role": "user", "content": user}])
            if think_on:
                base["thinking"] = {"type": "adaptive"}
                base["output_config"] = {"effort": "medium"}
            try:
                if think_on:
                    resp = client.messages.create(**base)
                else:
                    # Disable thinking for a clean, cheap JSON write (Sonnet 5 defaults to
                    # adaptive thinking, which eats max_tokens before the JSON finishes).
                    resp = client.messages.create(**base, thinking={"type": "disabled"})
            except Exception:
                try:
                    resp = client.messages.create(**base)  # model rejects param -> default
                except Exception as e:
                    print(f"  [{mkey}] ERROR: {str(e)[:120]}"); continue
            dt = time.time() - t0
            text = next((b.text for b in resp.content if b.type == "text"), "")
            obj = extract_json(text)
            c, (it, ci, cr, ot) = cost(resp.usage, in_rate, out_rate)
            total += c
            safe_dom = re.sub(r"[^\w]+", "_", dom).strip("_")
            tag = mkey + ("_think" if think_on else "")
            (OUTDIR / f"{safe_dom}__{tag}.json").write_text(
                json.dumps(obj, indent=2) if obj else text)
            ok = "ok" if obj else "PARSE-FAIL"
            print(f"  [{tag:11} {model_id}] {ok}  {dt:4.1f}s  "
                  f"in={it} cache_w={ci} cache_r={cr} out={ot}  ${c:.4f}")

    print(f"\nTOTAL TEST COST: ${total:.4f}   (outputs saved in {OUTDIR.relative_to(ROOT)}/)")
    print("Extrapolated batch cost for 380 = per-prospect output-cost x 380 x 0.5 (Batch API).")


if __name__ == "__main__":
    main()
