"""Lightweight Gemini token-usage logger for cost measurement.
Appends 'label,prompt_tokens,output_tokens,total_tokens' lines to a log file
(default /tmp/grader_tokens.log). total includes thinking tokens; output is
computed as total-prompt so thinking is counted at the output rate."""
import os

TOKEN_LOG = os.getenv('TOKEN_LOG', '/tmp/grader_tokens.log')


def log_usage(label, response):
    try:
        u = getattr(response, 'usage_metadata', None)
        if u is None:
            return
        p = int(getattr(u, 'prompt_token_count', 0) or 0)
        t = int(getattr(u, 'total_token_count', 0) or 0)
        out = max(t - p, int(getattr(u, 'candidates_token_count', 0) or 0))
        with open(TOKEN_LOG, 'a') as f:
            f.write(f"{label},{p},{out},{t}\n")
    except Exception:
        pass
